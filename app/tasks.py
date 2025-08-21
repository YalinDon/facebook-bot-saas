<<<<<<< HEAD
# app/tasks.py (Version Centralisée Complète)

import time
import json
import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from facebook import GraphAPI
from selenium.common.exceptions import TimeoutException
from datetime import datetime

from app import scheduler, db
from app.models import User, FacebookPage, Broadcast, PublishedNews
from app.services import EncryptionService

# --- Configuration Globale du Scraping ---
LIVE_URL = "https://www.matchendirect.fr/live-score/"
FINISHED_URL = "https://www.matchendirect.fr/live-foot/"

# --- GESTION DE L'ÉTAT CENTRALISÉ (Fichiers JSON à la racine du projet) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DATA_FILE = os.path.join(BASE_DIR, 'scores.json')
PUBLISHED_FINISHED_FILE = os.path.join(BASE_DIR, 'published_finished.json')

# --- Gestion de l'instance de l'application ---
_app = None

def init_app(app):
    global _app
    _app = app

# =============================================================================
# === FONCTIONS UTILITAIRES DE BASE ===========================================
# =============================================================================



def get_browser():
    """Initialise et retourne une instance du navigateur Selenium plus robuste."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    # --- AJOUTS POUR LA STABILITÉ ET LA PERFORMANCE ---
    # 1. Désactive le chargement des images. C'est la modification la plus efficace.
    options.add_argument('--blink-settings=imagesEnabled=false')
    # 2. Options supplémentaires pour éviter les plantages liés à l'interface graphique
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-popup-blocking')
    # --- FIN DES AJOUTS ---
    
    try:
        service = Service() 
        driver = webdriver.Chrome(service=service, options=options)
        # On définit un timeout de page global pour éviter que driver.get() ne bloque indéfiniment
        driver.set_page_load_timeout(60) # 60 secondes max pour charger une page
        return driver
    except Exception as e:
        print(f"[ERREUR SELENIUM] Impossible de démarrer le navigateur : {e}")
        return None

def load_from_json(filepath):
    """Charge les données depuis un fichier JSON."""
    default = [] if "published" in filepath else {}
    if not os.path.exists(filepath): return default
    try:
        with open(filepath, "r", encoding='utf-8') as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return default

def save_to_json(data, filepath):
    """Sauvegarde les données dans un fichier JSON."""
    with open(filepath, "w", encoding='utf-8') as f: json.dump(data, f, indent=4)



# =============================================================================
# === FONCTIONS DE SCRAPING (INCHANGÉES) ======================================
# =============================================================================
def get_live_scores(driver):
    print("🔎 Scraping des scores en direct...")
    scores = {}
    try:
        driver.get(LIVE_URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "td.lm3")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        match_blocks = soup.select("td.lm3")
        for match in match_blocks:
            try:
                eq1, eq2 = match.select_one("span.lm3_eq1").text.strip(), match.select_one("span.lm3_eq2").text.strip()
                score1, score2 = match.select_one("span.scored_1").text.strip(), match.select_one("span.scored_2").text.strip()
                row = match.find_parent("tr")
                minute = row.select_one("td.lm2").text.strip() if row.select_one("td.lm2") else ""
                link = row.select_one("a")
                url = f"https://www.matchendirect.fr{link.get('href')}" if link and link.get('href') else None
                statut = "MT" if "mi-temps" in minute.lower() or "mt" in minute.lower() else ("TER" if "ter" in minute.lower() else "")
                key = f"{eq1} vs {eq2}"
                scores[key] = {"score": f"{score1} - {score2}", "statut": statut, "minute": minute, "eq1": eq1, "eq2": eq2, "url": url}
            except Exception: pass
    except Exception as e: print(f"[ERREUR SELENIUM - get_live_scores] {e}")
    print(f"✅ {len(scores)} scores en direct trouvés.")
    return scores

def get_match_details(driver, match_url):
    if not match_url: return None, None
    try:
        driver.get(match_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.st1.eventTypeG")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        rows = soup.select("tr")
        for row in reversed(rows):
            if row.select_one("span.st1.eventTypeG"):
                buteur_el = row.select_one("span.st1.eventTypeG")
                minute_el = row.select_one("td.c2")
                buteur = buteur_el.text.strip() if buteur_el else None
                minute = minute_el.text.strip() if minute_el else None
                return buteur, minute
    except Exception: pass
    return None, None
    
def get_stat_url(match_url):
    if not match_url: return None
    return f"{match_url.split('?')[0]}?p=stats"

def get_match_stats(driver, stat_url):
    if not stat_url: return ""
    try:
        driver.get(stat_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.progressBar")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        blocks, stats, seen_titles = soup.select("div.progressBar"), [], set()
        for block in blocks:
            titre_el, v1_el, v2_el = block.select_one("h5.progressHeaderTitle"), block.select_one("span.progressBarValue1"), block.select_one("span.progressBarValue2")
            if titre_el and v1_el and v2_el:
                titre_text = titre_el.text.strip()
                if titre_text in seen_titles: continue
                seen_titles.add(titre_text)
                stats.append(f"{titre_text} : {v1_el.text.strip()} - {v2_el.text.strip()}")
        return "\n📊 " + "\n📊 ".join(stats) if stats else ""
    except Exception as e: print(f"[ERREUR STATS] {e}")
    return ""

def get_penalty_shootout_score(driver, match_url):
    if not match_url: return None
    try:
        driver.get(match_url)
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, "//td[contains(text(), 'Penalties')]")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        penalty_cell = soup.find("td", string=lambda text: "Penalties" in text if text else False)
        if penalty_cell and penalty_cell.find("b"):
            score_penalties = penalty_cell.find("b").text.strip()
            print(f"🎯 Tirs au but trouvés : {score_penalties}")
            return f"Tirs au but : {score_penalties}"
    except TimeoutException: print("...Aucune séance de tirs au but détectée.")
    except Exception as e: print(f"[AVERTISSEMENT] Erreur T.A.B : {e}")
    return None


def broadcast_to_facebook(active_pages, message, encryption_service):
    """Enregistre le message dans l'historique et le publie sur les pages actives."""
    
    # --- DÉBUT DE L'AJOUT ---
    # On enregistre le message dans la base de données AVANT de l'envoyer.
    # Le _app.app_context() est nécessaire car cette fonction est appelée
    # depuis la tâche principale qui a déjà le contexte.
    try:
        new_broadcast = Broadcast(content=message)
        db.session.add(new_broadcast)
        db.session.commit()
        print(f"[HISTORIQUE] Message enregistré: {message[:60]}...")
    except Exception as e:
        db.session.rollback()
        print(f"[HISTORIQUE ERREUR] Impossible d'enregistrer le message : {e}")
        # On continue même si l'enregistrement échoue, la publication est plus importante.
    # --- FIN DE L'AJOUT ---
    
    if not active_pages:
        print(f"[BROADCAST IGNORÉ] Aucun auditeur actif pour le message : {message[:60]}...")
        return
        
    print(f"[BROADCAST] Envoi du message à {len(active_pages)} page(s) : {message[:60]}...")
    for page in active_pages:
        try:
            decrypted_token = encryption_service.decrypt(page.encrypted_page_access_token)
            graph = GraphAPI(access_token=decrypted_token)
            graph.put_object(parent_object=page.facebook_page_id, connection_name="feed", message=message)
            print(f"  -> Succès pour '{page.page_name}'")
        except Exception as e:
            print(f"  -> ERREUR pour '{page.page_name}': {e}")
# Dans app/tasks.py

def check_expired_subscriptions():
    """Tâche nocturne qui vérifie et désactive les abonnements expirés."""
    if _app is None: return
    with _app.app_context():
        now = datetime.utcnow()
        print(f"\n--- [{now.strftime('%Y-%m-%d %H:%M:%S')}] Démarrage de la vérification des abonnements expirés ---")

        # On cherche les utilisateurs dont l'abonnement est actif ET dont la date d'expiration est dans le passé
        expired_users = User.query.filter(
            User.subscription_status == 'active',
            User.subscription_expires_at != None,
            User.subscription_expires_at < now
        ).all()

        if not expired_users:
            print("Aucun abonnement expiré trouvé.")
            return

        print(f"Trouvé {len(expired_users)} abonnement(s) expiré(s) à désactiver...")
        for user in expired_users:
            user.subscription_status = 'inactive'
            user.subscription_plan = None
            print(f" -> Abonnement désactivé pour {user.email}")
            # Ici, on pourrait ajouter une notification pour prévenir l'utilisateur

        db.session.commit()
        print("--- Vérification des abonnements expirés terminée ---")
# =============================================================================
# === TÂCHE PLANIFIÉE PRINCIPALE (LOGIQUE CENTRALISÉE) ========================
# =============================================================================

# Dans app/tasks.py

def get_article_content(driver, article_url):
    """Visite la page d'un article et en extrait le contenu textuel."""
    try:
        # --- DÉBUT DE LA MODIFICATION ---
        # Stratégie de chargement "Eager" :
        # On dit à Selenium de ne pas attendre que TOUT soit chargé (images, pubs...).
        # Il continue dès que le HTML de base (DOM) est prêt.
        driver.execute_script("window.stop();") # Arrête le chargement en cours si besoin
        driver.get(article_url)
        # --- FIN DE LA MODIFICATION ---

        # On attend que le corps de l'article soit présent
        article_body_selector = "#cont12 p.par1"
        article_body = WebDriverWait(driver, 20).until( # On donne 20s pour trouver l'élément
            EC.presence_of_element_located((By.CSS_SELECTOR, article_body_selector))
        )
        content = article_body.get_attribute('innerText').strip()
        
        if len(content) > 1500:
            content = content[:1500] + "..."
        return content
    except Exception as e:
        # On capture l'erreur de timeout spécifique pour un message plus clair
        if isinstance(e, TimeoutException):
            print(f"   -> Avertissement: Timeout en attendant le contenu de l'article {article_url}")
        else:
            print(f"   -> Avertissement: Impossible de scraper le contenu de {article_url}. Erreur: {e}")
        return None

# Dans app/tasks.py

def scrape_football_news(driver):
    """Scrape les brèves de Maxifoot.fr, et ne garde que celles dont le contenu a pu être extrait."""
    print("📰 Scraping des actualités du football...")
    news_list = []
    try:
        driver.get("https://www.maxifoot.fr/")
        
        try: # Gestion du pop-up de cookies
            cookie_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button")))
            cookie_button.click()
            print("   -> Pop-up de cookies accepté.")
            time.sleep(1)
        except TimeoutException:
            print("   -> Pas de pop-up de cookies détecté.")

        main_container_selector = "div.listegen5.listeInfo3"
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, main_container_selector)))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        main_container = soup.select_one(main_container_selector)
        if not main_container:
            print("[ERREUR SCRAPING NEWS] Conteneur principal non trouvé.")
            return []

        article_links = main_container.find_all("a", href=True)
        
        for link_tag in article_links:
            if "Voir les brèves précédentes" in link_tag.get_text():
                continue

            time_tag = link_tag.find('b')
            if time_tag: time_tag.extract()
            
            title = link_tag.get_text(strip=True)
            url = link_tag['href']
            
            if not url.startswith('http'):
                url = "https://news.maxifoot.fr/" + url.lstrip('/')

            # --- DÉBUT DE LA CORRECTION ---
            # On va chercher le contenu de l'article
            content = get_article_content(driver, url)
            
            # On ajoute l'article à la liste SEULEMENT SI le contenu a été trouvé
            if content:
                news_list.append({'title': title, 'url': url, 'content': content})
            # --- FIN DE LA CORRECTION ---
        
        print(f"✅ {len(news_list)} actualités avec contenu trouvées.")
        return news_list
        
    except Exception as e:
        print(f"[ERREUR SCRAPING NEWS] Une erreur est survenue : {e}")
        return []

# Dans app/tasks.py

def post_live_scores_summary():
    """
    Tâche périodique qui publie un résumé de tous les matchs en cours.
    """
    if _app is None: return
    with _app.app_context():
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Démarrage de la publication du résumé des scores ---")

        # On récupère la liste des pages éligibles (comme dans les autres tâches)
        now = datetime.utcnow()
        active_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(
                User.role == 'superadmin',
                User.subscription_status == 'active',
                User.trial_ends_at > now
            )
        ).all()

        if not active_pages:
            print("Aucune page active pour le résumé. Tâche terminée.")
            return

        # On charge l'état actuel des scores depuis le fichier JSON
        scores = load_from_json(LIVE_DATA_FILE)
        if not scores:
            print("Aucun score en direct à résumer.")
            return

        # On construit le message de résumé (logique de votre script original)
        message, matchs_en_cours = "📊 Scores en direct :\n\n", 0
        for match_key, data in scores.items():
            if data.get("statut") != "TER":
                eq1, eq2 = data.get("eq1"), data.get("eq2")
                if not eq1 or not eq2: continue # Sécurité
                
                ligne = f"{eq1} {data['score']} {eq2}"
                
                if data.get('statut') == "MT":
                    ligne += " (MT)"
                elif "'" in data.get('minute', ''):
                    ligne += f" ({data['minute']})"
                    
                message += f"◉ {ligne}\n"
                matchs_en_cours += 1
        
        # On ne publie que s'il y a au moins un match en cours
        if matchs_en_cours > 0:
            encryption_service = EncryptionService()
            broadcast_to_facebook(active_pages, message.strip(), encryption_service)
        else:
            print("Aucun match en cours à résumer.")
        
        print("--- Publication du résumé terminée ---")



def run_centralized_checks():
    if _app is None: return
    with _app.app_context():
        start_time = time.time()
        print(f"\n--- [{time.strftime('%Y-%m-%d %H:%M:%S')}] Démarrage du cycle de vérification centralisé ---")
        
        now = datetime.utcnow()
        active_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(
                User.role == 'superadmin',
                User.subscription_status == 'active',
                User.trial_ends_at > now
            )
        ).all()

        if not active_pages:
            print("Aucune page active ou en période d'essai. Le bot tourne en silence pour maintenir l'état à jour.")
        else:
            print(f"{len(active_pages)} page(s) écoute(nt) le flux de publication.")

        encryption_service = EncryptionService()
        driver = get_browser()
        if not driver: return

        try:
            # --- LOGIQUE DE VOTRE SCRIPT ORIGINAL ---
            
            # 1. Traitement des matchs en direct
            old_scores = load_from_json(LIVE_DATA_FILE)
            new_scores = get_live_scores(driver)
            
            for match_key, new_data in new_scores.items():
                new_score, new_statut, minute, eq1, eq2, url = new_data.values()
                
                if match_key not in old_scores:
                    if new_score != " - " and "'" in minute:
                        message = f"⏱️ {minute}\n{eq1} {new_score} {eq2}"
                        broadcast_to_facebook(active_pages, message, encryption_service)
                    continue

                old_data = old_scores[match_key]
                changement_score = new_score != old_data.get("score")
                changement_statut_mt = new_statut == "MT" and old_data.get("statut") != "MT"

                if changement_statut_mt:
                    msg = f"⏸️ Mi-temps\n{eq1} {new_score} {eq2}"
                    stats = get_match_stats(driver, get_stat_url(url))
                    broadcast_to_facebook(active_pages, f"{msg}\n\n{stats}".strip(), encryption_service)
                elif changement_score:
                    try:
                        old_score_str = old_data.get("score")
                        if not old_score_str or "-" not in old_score_str or "-" not in new_score: continue
                        s1_old, s2_old = map(int, old_score_str.split(" - "))
                        s1_new, s2_new = map(int, new_score.split(" - "))

                        if s1_new > s1_old or s2_new > s2_old: # But marqué
                            equipe_but = eq1 if s1_new > s1_old else eq2
                            buteur_brut, minute_but = get_match_details(driver, url)
                            msg_buteur = ""
                            if buteur_brut:
                                if buteur_brut.startswith('('): msg_buteur = f"🚀 Buuuut de {equipe_but} !"
                                elif '(' in buteur_brut:
                                    nom_propre = f"{buteur_brut.split('(')[0].strip()} 🔥"
                                    msg_buteur = f"🚀 Buuuut de {nom_propre} ({equipe_but}) !"
                                else: msg_buteur = f"🚀 Buuuut de {buteur_brut} ({equipe_but}) !"
                            else: msg_buteur = f"🚀 Buuuut de {equipe_but} !"
                            minute_affiche = minute_but if minute_but else minute
                            broadcast_to_facebook(active_pages, f"{msg_buteur}\n⏱️ {minute_affiche}\n{eq1} {new_score} {eq2}", encryption_service)
                        elif s1_new < s1_old or s2_new < s2_old: # But refusé
                            msg = f"❌ BUT REFUSÉ pour {eq1 if s1_new < s1_old else eq2} après consultation de la VAR.\n\nLe score revient à {eq1} {new_score} {eq2}"
                            broadcast_to_facebook(active_pages, msg, encryption_service)
                    except (ValueError, IndexError): continue
            
            save_to_json(new_scores, LIVE_DATA_FILE)

            # 2. Traitement des matchs terminés
            previously_published_ids = set(load_from_json(PUBLISHED_FINISHED_FILE))
            driver.get(FINISHED_URL)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tr[data-matchid]")))
            soup = BeautifulSoup(driver.page_source, "html.parser")
            match_rows = soup.select("tr[data-matchid]")
            
            for row in match_rows:
                if "TER" in (row.select_one("td.lm2").text or ""):
                    match_id = row['data-matchid']
                    if match_id not in previously_published_ids:
                        try:
                            eq1, eq2, score = row.select_one("span.lm3_eq1").text.strip(), row.select_one("span.lm3_eq2").text.strip(), row.select_one("span.lm3_score").text.strip()
                            url = f"https://www.matchendirect.fr{row.select_one('a.ga4-matchdetail').get('href')}"
                            
                            print(f"✨ Nouveau match terminé détecté: {eq1} vs {eq2}")
                            msg = f"🔚 Terminé\n{eq1} {score} {eq2}"
                            penalty_text = get_penalty_shootout_score(driver, url)
                            if penalty_text: msg += f"\n{penalty_text}"
                            
                            stats = get_match_stats(driver, get_stat_url(url))
                            broadcast_to_facebook(active_pages, f"{msg}\n\n{stats}".strip(), encryption_service)
                            
                            previously_published_ids.add(match_id)
                        except Exception as e: print(f"❌ Erreur sur traitement match terminé {match_id}: {e}")
            
            save_to_json(list(previously_published_ids), PUBLISHED_FINISHED_FILE)
            
        except Exception as e:
            print(f"ERREUR MAJEURE dans run_centralized_checks: {e}")
        finally:
            driver.quit()
            duration = time.time() - start_time
            print(f"--- Cycle centralisé terminé en {duration:.2f} secondes ---")



# Dans app/tasks.py

# Dans app/tasks.py

def publish_news_for_business_users():
    """
    Tâche qui scrape les actualités et les publie UNIQUEMENT pour les abonnés Business.
    Enregistre les publications dans l'historique unifié (table Broadcast).
    """
    if _app is None: return
    with _app.app_context():
        start_time = time.time()
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Démarrage de la publication des actualités ---")

        # 1. On récupère UNIQUEMENT les pages des abonnés "Business" actifs
        business_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(
                User.role == 'superadmin', # Le superadmin reçoit aussi les actus
                User.subscription_plan == 'business'
            )
        ).all()

        if not business_pages:
            print("Aucun abonné Business actif. Tâche terminée.")
            return

        print(f"Ciblage de {len(business_pages)} page(s) pour la publication des actualités.")
        encryption_service = EncryptionService()
        driver = get_browser()
        if not driver: return

        try:
            # 2. On scrape les dernières news avec leur contenu complet
            latest_news = scrape_football_news(driver)
            if not latest_news:
                return

            # 3. On récupère les URL des news déjà publiées pour éviter les doublons
            published_urls = {news.article_url for news in PublishedNews.query.all()}

            # 4. On filtre pour ne garder que les nouvelles actualités
            news_to_publish = []
            for news in reversed(latest_news): # On inverse pour publier les plus anciennes en premier
                if news['url'] not in published_urls:
                    news_to_publish.append(news)
            
            if news_to_publish:
                print(f"-> {len(news_to_publish)} nouvelle(s) actualité(s) à publier :")
                for news in news_to_publish:
                    print(f"   - TITRE: {news['title']}")
            else:
                print("Aucune nouvelle actualité à publier.")
            
            for news in news_to_publish:
                # 5. On construit le message final, sans la source
                message = f"🚨 **ACTU FOOT** 🚨\n\n**{news['title']}**\n\n{news['content']}"
                
                # 6. On utilise broadcast_to_facebook. Cette fonction va :
                #    a) Enregistrer le message dans la table 'Broadcast'
                #    b) Publier le message sur toutes les pages 'business_pages'
                broadcast_to_facebook(business_pages, message, encryption_service)
                
                # 7. On enregistre la news dans la table de contrôle 'PublishedNews' 
                #    pour s'assurer qu'elle ne sera plus jamais traitée.
                #    On n'a plus besoin de stocker le contenu ici.
                new_published_news = PublishedNews(article_url=news['url'], title=news['title'])
                db.session.add(new_published_news)
                db.session.commit()
                
                # Petite pause pour ne pas surcharger l'API de Facebook
                time.sleep(10)

        finally:
            driver.quit()
            duration = time.time() - start_time
            print(f"--- Publication des actualités terminée en {duration:.2f} secondes ---")


# =============================================================================
# === ENREGISTREMENT DES TÂCHES ===============================================
# =============================================================================

if scheduler.get_job('centralized_checks_job'):
    scheduler.remove_job('centralized_checks_job')
if scheduler.get_job('summary_post_job'): # Supprime l'ancienne tâche de résumé si elle existe
    scheduler.remove_job('summary_post_job')
if scheduler.get_job('main_scraping_job'): # Supprime l'ancienne tâche si elle existe
    scheduler.remove_job('main_scraping_job')


scheduler.add_job(
    id='centralized_checks_job', 
    func=run_centralized_checks, 
    trigger='interval', 
    minutes=2,
    replace_existing=True
)

# À la fin de app/tasks.py, dans la section d'enregistrement

if not scheduler.get_job('check_expired_job'):
    scheduler.add_job(
        id='check_expired_job',
        func=check_expired_subscriptions,
        trigger='cron', # Se déclenche à une heure précise
        hour=1, # Tous les jours à 1h du matin (heure du serveur)
        minute=5
    )
    
    

# ... (l'enregistrement de centralized_checks_job) ...

if not scheduler.get_job('publish_news_job'):
    scheduler.add_job(
        id='publish_news_job', 
        func=publish_news_for_business_users, 
        trigger='interval', 
        minutes=15 # Par exemple, toutes les 15 minutes
    )
    
    
if not scheduler.get_job('live_summary_job'):
    scheduler.add_job(
        id='live_summary_job', 
        func=post_live_scores_summary, 
        trigger='interval', 
        minutes=30
=======
# app/tasks.py (Version Centralisée Complète)

import time
import json
import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from facebook import GraphAPI
from selenium.common.exceptions import TimeoutException
from datetime import datetime

from app import scheduler, db
from app.models import User, FacebookPage, Broadcast, PublishedNews
from app.services import EncryptionService

# --- Configuration Globale du Scraping ---
LIVE_URL = "https://www.matchendirect.fr/live-score/"
FINISHED_URL = "https://www.matchendirect.fr/live-foot/"

# --- GESTION DE L'ÉTAT CENTRALISÉ (Fichiers JSON à la racine du projet) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DATA_FILE = os.path.join(BASE_DIR, 'scores.json')
PUBLISHED_FINISHED_FILE = os.path.join(BASE_DIR, 'published_finished.json')

# --- Gestion de l'instance de l'application ---
_app = None

def init_app(app):
    global _app
    _app = app

# =============================================================================
# === FONCTIONS UTILITAIRES DE BASE ===========================================
# =============================================================================



def get_browser():
    """Initialise et retourne une instance du navigateur Selenium plus robuste."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    # --- AJOUTS POUR LA STABILITÉ ET LA PERFORMANCE ---
    # 1. Désactive le chargement des images. C'est la modification la plus efficace.
    options.add_argument('--blink-settings=imagesEnabled=false')
    # 2. Options supplémentaires pour éviter les plantages liés à l'interface graphique
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-popup-blocking')
    # --- FIN DES AJOUTS ---
    
    try:
        service = Service() 
        driver = webdriver.Chrome(service=service, options=options)
        # On définit un timeout de page global pour éviter que driver.get() ne bloque indéfiniment
        driver.set_page_load_timeout(60) # 60 secondes max pour charger une page
        return driver
    except Exception as e:
        print(f"[ERREUR SELENIUM] Impossible de démarrer le navigateur : {e}")
        return None

def load_from_json(filepath):
    """Charge les données depuis un fichier JSON."""
    default = [] if "published" in filepath else {}
    if not os.path.exists(filepath): return default
    try:
        with open(filepath, "r", encoding='utf-8') as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return default

def save_to_json(data, filepath):
    """Sauvegarde les données dans un fichier JSON."""
    with open(filepath, "w", encoding='utf-8') as f: json.dump(data, f, indent=4)



# =============================================================================
# === FONCTIONS DE SCRAPING (INCHANGÉES) ======================================
# =============================================================================
def get_live_scores(driver):
    print("🔎 Scraping des scores en direct...")
    scores = {}
    try:
        driver.get(LIVE_URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "td.lm3")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        match_blocks = soup.select("td.lm3")
        for match in match_blocks:
            try:
                eq1, eq2 = match.select_one("span.lm3_eq1").text.strip(), match.select_one("span.lm3_eq2").text.strip()
                score1, score2 = match.select_one("span.scored_1").text.strip(), match.select_one("span.scored_2").text.strip()
                row = match.find_parent("tr")
                minute = row.select_one("td.lm2").text.strip() if row.select_one("td.lm2") else ""
                link = row.select_one("a")
                url = f"https://www.matchendirect.fr{link.get('href')}" if link and link.get('href') else None
                statut = "MT" if "mi-temps" in minute.lower() or "mt" in minute.lower() else ("TER" if "ter" in minute.lower() else "")
                key = f"{eq1} vs {eq2}"
                scores[key] = {"score": f"{score1} - {score2}", "statut": statut, "minute": minute, "eq1": eq1, "eq2": eq2, "url": url}
            except Exception: pass
    except Exception as e: print(f"[ERREUR SELENIUM - get_live_scores] {e}")
    print(f"✅ {len(scores)} scores en direct trouvés.")
    return scores

def get_match_details(driver, match_url):
    if not match_url: return None, None
    try:
        driver.get(match_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.st1.eventTypeG")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        rows = soup.select("tr")
        for row in reversed(rows):
            if row.select_one("span.st1.eventTypeG"):
                buteur_el = row.select_one("span.st1.eventTypeG")
                minute_el = row.select_one("td.c2")
                buteur = buteur_el.text.strip() if buteur_el else None
                minute = minute_el.text.strip() if minute_el else None
                return buteur, minute
    except Exception: pass
    return None, None
    
def get_stat_url(match_url):
    if not match_url: return None
    return f"{match_url.split('?')[0]}?p=stats"

def get_match_stats(driver, stat_url):
    if not stat_url: return ""
    try:
        driver.get(stat_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.progressBar")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        blocks, stats, seen_titles = soup.select("div.progressBar"), [], set()
        for block in blocks:
            titre_el, v1_el, v2_el = block.select_one("h5.progressHeaderTitle"), block.select_one("span.progressBarValue1"), block.select_one("span.progressBarValue2")
            if titre_el and v1_el and v2_el:
                titre_text = titre_el.text.strip()
                if titre_text in seen_titles: continue
                seen_titles.add(titre_text)
                stats.append(f"{titre_text} : {v1_el.text.strip()} - {v2_el.text.strip()}")
        return "\n📊 " + "\n📊 ".join(stats) if stats else ""
    except Exception as e: print(f"[ERREUR STATS] {e}")
    return ""

def get_penalty_shootout_score(driver, match_url):
    if not match_url: return None
    try:
        driver.get(match_url)
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, "//td[contains(text(), 'Penalties')]")))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        penalty_cell = soup.find("td", string=lambda text: "Penalties" in text if text else False)
        if penalty_cell and penalty_cell.find("b"):
            score_penalties = penalty_cell.find("b").text.strip()
            print(f"🎯 Tirs au but trouvés : {score_penalties}")
            return f"Tirs au but : {score_penalties}"
    except TimeoutException: print("...Aucune séance de tirs au but détectée.")
    except Exception as e: print(f"[AVERTISSEMENT] Erreur T.A.B : {e}")
    return None


def broadcast_to_facebook(active_pages, message, encryption_service):
    """Enregistre le message dans l'historique et le publie sur les pages actives."""
    
    # --- DÉBUT DE L'AJOUT ---
    # On enregistre le message dans la base de données AVANT de l'envoyer.
    # Le _app.app_context() est nécessaire car cette fonction est appelée
    # depuis la tâche principale qui a déjà le contexte.
    try:
        new_broadcast = Broadcast(content=message)
        db.session.add(new_broadcast)
        db.session.commit()
        print(f"[HISTORIQUE] Message enregistré: {message[:60]}...")
    except Exception as e:
        db.session.rollback()
        print(f"[HISTORIQUE ERREUR] Impossible d'enregistrer le message : {e}")
        # On continue même si l'enregistrement échoue, la publication est plus importante.
    # --- FIN DE L'AJOUT ---
    
    if not active_pages:
        print(f"[BROADCAST IGNORÉ] Aucun auditeur actif pour le message : {message[:60]}...")
        return
        
    print(f"[BROADCAST] Envoi du message à {len(active_pages)} page(s) : {message[:60]}...")
    for page in active_pages:
        try:
            decrypted_token = encryption_service.decrypt(page.encrypted_page_access_token)
            graph = GraphAPI(access_token=decrypted_token)
            graph.put_object(parent_object=page.facebook_page_id, connection_name="feed", message=message)
            print(f"  -> Succès pour '{page.page_name}'")
        except Exception as e:
            print(f"  -> ERREUR pour '{page.page_name}': {e}")
# Dans app/tasks.py

def check_expired_subscriptions():
    """Tâche nocturne qui vérifie et désactive les abonnements expirés."""
    if _app is None: return
    with _app.app_context():
        now = datetime.utcnow()
        print(f"\n--- [{now.strftime('%Y-%m-%d %H:%M:%S')}] Démarrage de la vérification des abonnements expirés ---")

        # On cherche les utilisateurs dont l'abonnement est actif ET dont la date d'expiration est dans le passé
        expired_users = User.query.filter(
            User.subscription_status == 'active',
            User.subscription_expires_at != None,
            User.subscription_expires_at < now
        ).all()

        if not expired_users:
            print("Aucun abonnement expiré trouvé.")
            return

        print(f"Trouvé {len(expired_users)} abonnement(s) expiré(s) à désactiver...")
        for user in expired_users:
            user.subscription_status = 'inactive'
            user.subscription_plan = None
            print(f" -> Abonnement désactivé pour {user.email}")
            # Ici, on pourrait ajouter une notification pour prévenir l'utilisateur

        db.session.commit()
        print("--- Vérification des abonnements expirés terminée ---")
# =============================================================================
# === TÂCHE PLANIFIÉE PRINCIPALE (LOGIQUE CENTRALISÉE) ========================
# =============================================================================

# Dans app/tasks.py

def get_article_content(driver, article_url):
    """Visite la page d'un article et en extrait le contenu textuel."""
    try:
        # --- DÉBUT DE LA MODIFICATION ---
        # Stratégie de chargement "Eager" :
        # On dit à Selenium de ne pas attendre que TOUT soit chargé (images, pubs...).
        # Il continue dès que le HTML de base (DOM) est prêt.
        driver.execute_script("window.stop();") # Arrête le chargement en cours si besoin
        driver.get(article_url)
        # --- FIN DE LA MODIFICATION ---

        # On attend que le corps de l'article soit présent
        article_body_selector = "#cont12 p.par1"
        article_body = WebDriverWait(driver, 20).until( # On donne 20s pour trouver l'élément
            EC.presence_of_element_located((By.CSS_SELECTOR, article_body_selector))
        )
        content = article_body.get_attribute('innerText').strip()
        
        if len(content) > 1500:
            content = content[:1500] + "..."
        return content
    except Exception as e:
        # On capture l'erreur de timeout spécifique pour un message plus clair
        if isinstance(e, TimeoutException):
            print(f"   -> Avertissement: Timeout en attendant le contenu de l'article {article_url}")
        else:
            print(f"   -> Avertissement: Impossible de scraper le contenu de {article_url}. Erreur: {e}")
        return None

# Dans app/tasks.py

def scrape_football_news(driver):
    """Scrape les brèves de Maxifoot.fr, et ne garde que celles dont le contenu a pu être extrait."""
    print("📰 Scraping des actualités du football...")
    news_list = []
    try:
        driver.get("https://www.maxifoot.fr/")
        
        try: # Gestion du pop-up de cookies
            cookie_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button")))
            cookie_button.click()
            print("   -> Pop-up de cookies accepté.")
            time.sleep(1)
        except TimeoutException:
            print("   -> Pas de pop-up de cookies détecté.")

        main_container_selector = "div.listegen5.listeInfo3"
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, main_container_selector)))
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        main_container = soup.select_one(main_container_selector)
        if not main_container:
            print("[ERREUR SCRAPING NEWS] Conteneur principal non trouvé.")
            return []

        article_links = main_container.find_all("a", href=True)
        
        for link_tag in article_links:
            if "Voir les brèves précédentes" in link_tag.get_text():
                continue

            time_tag = link_tag.find('b')
            if time_tag: time_tag.extract()
            
            title = link_tag.get_text(strip=True)
            url = link_tag['href']
            
            if not url.startswith('http'):
                url = "https://news.maxifoot.fr/" + url.lstrip('/')

            # --- DÉBUT DE LA CORRECTION ---
            # On va chercher le contenu de l'article
            content = get_article_content(driver, url)
            
            # On ajoute l'article à la liste SEULEMENT SI le contenu a été trouvé
            if content:
                news_list.append({'title': title, 'url': url, 'content': content})
            # --- FIN DE LA CORRECTION ---
        
        print(f"✅ {len(news_list)} actualités avec contenu trouvées.")
        return news_list
        
    except Exception as e:
        print(f"[ERREUR SCRAPING NEWS] Une erreur est survenue : {e}")
        return []

# Dans app/tasks.py

def post_live_scores_summary():
    """
    Tâche périodique qui publie un résumé de tous les matchs en cours.
    """
    if _app is None: return
    with _app.app_context():
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Démarrage de la publication du résumé des scores ---")

        # On récupère la liste des pages éligibles (comme dans les autres tâches)
        now = datetime.utcnow()
        active_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(
                User.role == 'superadmin',
                User.subscription_status == 'active',
                User.trial_ends_at > now
            )
        ).all()

        if not active_pages:
            print("Aucune page active pour le résumé. Tâche terminée.")
            return

        # On charge l'état actuel des scores depuis le fichier JSON
        scores = load_from_json(LIVE_DATA_FILE)
        if not scores:
            print("Aucun score en direct à résumer.")
            return

        # On construit le message de résumé (logique de votre script original)
        message, matchs_en_cours = "📊 Scores en direct :\n\n", 0
        for match_key, data in scores.items():
            if data.get("statut") != "TER":
                eq1, eq2 = data.get("eq1"), data.get("eq2")
                if not eq1 or not eq2: continue # Sécurité
                
                ligne = f"{eq1} {data['score']} {eq2}"
                
                if data.get('statut') == "MT":
                    ligne += " (MT)"
                elif "'" in data.get('minute', ''):
                    ligne += f" ({data['minute']})"
                    
                message += f"◉ {ligne}\n"
                matchs_en_cours += 1
        
        # On ne publie que s'il y a au moins un match en cours
        if matchs_en_cours > 0:
            encryption_service = EncryptionService()
            broadcast_to_facebook(active_pages, message.strip(), encryption_service)
        else:
            print("Aucun match en cours à résumer.")
        
        print("--- Publication du résumé terminée ---")



def run_centralized_checks():
    if _app is None: return
    with _app.app_context():
        start_time = time.time()
        print(f"\n--- [{time.strftime('%Y-%m-%d %H:%M:%S')}] Démarrage du cycle de vérification centralisé ---")
        
        now = datetime.utcnow()
        active_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(
                User.role == 'superadmin',
                User.subscription_status == 'active',
                User.trial_ends_at > now
            )
        ).all()

        if not active_pages:
            print("Aucune page active ou en période d'essai. Le bot tourne en silence pour maintenir l'état à jour.")
        else:
            print(f"{len(active_pages)} page(s) écoute(nt) le flux de publication.")

        encryption_service = EncryptionService()
        driver = get_browser()
        if not driver: return

        try:
            # --- LOGIQUE DE VOTRE SCRIPT ORIGINAL ---
            
            # 1. Traitement des matchs en direct
            old_scores = load_from_json(LIVE_DATA_FILE)
            new_scores = get_live_scores(driver)
            
            for match_key, new_data in new_scores.items():
                new_score, new_statut, minute, eq1, eq2, url = new_data.values()
                
                if match_key not in old_scores:
                    if new_score != " - " and "'" in minute:
                        message = f"⏱️ {minute}\n{eq1} {new_score} {eq2}"
                        broadcast_to_facebook(active_pages, message, encryption_service)
                    continue

                old_data = old_scores[match_key]
                changement_score = new_score != old_data.get("score")
                changement_statut_mt = new_statut == "MT" and old_data.get("statut") != "MT"

                if changement_statut_mt:
                    msg = f"⏸️ Mi-temps\n{eq1} {new_score} {eq2}"
                    stats = get_match_stats(driver, get_stat_url(url))
                    broadcast_to_facebook(active_pages, f"{msg}\n\n{stats}".strip(), encryption_service)
                elif changement_score:
                    try:
                        old_score_str = old_data.get("score")
                        if not old_score_str or "-" not in old_score_str or "-" not in new_score: continue
                        s1_old, s2_old = map(int, old_score_str.split(" - "))
                        s1_new, s2_new = map(int, new_score.split(" - "))

                        if s1_new > s1_old or s2_new > s2_old: # But marqué
                            equipe_but = eq1 if s1_new > s1_old else eq2
                            buteur_brut, minute_but = get_match_details(driver, url)
                            msg_buteur = ""
                            if buteur_brut:
                                if buteur_brut.startswith('('): msg_buteur = f"🚀 Buuuut de {equipe_but} !"
                                elif '(' in buteur_brut:
                                    nom_propre = f"{buteur_brut.split('(')[0].strip()} 🔥"
                                    msg_buteur = f"🚀 Buuuut de {nom_propre} ({equipe_but}) !"
                                else: msg_buteur = f"🚀 Buuuut de {buteur_brut} ({equipe_but}) !"
                            else: msg_buteur = f"🚀 Buuuut de {equipe_but} !"
                            minute_affiche = minute_but if minute_but else minute
                            broadcast_to_facebook(active_pages, f"{msg_buteur}\n⏱️ {minute_affiche}\n{eq1} {new_score} {eq2}", encryption_service)
                        elif s1_new < s1_old or s2_new < s2_old: # But refusé
                            msg = f"❌ BUT REFUSÉ pour {eq1 if s1_new < s1_old else eq2} après consultation de la VAR.\n\nLe score revient à {eq1} {new_score} {eq2}"
                            broadcast_to_facebook(active_pages, msg, encryption_service)
                    except (ValueError, IndexError): continue
            
            save_to_json(new_scores, LIVE_DATA_FILE)

            # 2. Traitement des matchs terminés
            previously_published_ids = set(load_from_json(PUBLISHED_FINISHED_FILE))
            driver.get(FINISHED_URL)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tr[data-matchid]")))
            soup = BeautifulSoup(driver.page_source, "html.parser")
            match_rows = soup.select("tr[data-matchid]")
            
            for row in match_rows:
                if "TER" in (row.select_one("td.lm2").text or ""):
                    match_id = row['data-matchid']
                    if match_id not in previously_published_ids:
                        try:
                            eq1, eq2, score = row.select_one("span.lm3_eq1").text.strip(), row.select_one("span.lm3_eq2").text.strip(), row.select_one("span.lm3_score").text.strip()
                            url = f"https://www.matchendirect.fr{row.select_one('a.ga4-matchdetail').get('href')}"
                            
                            print(f"✨ Nouveau match terminé détecté: {eq1} vs {eq2}")
                            msg = f"🔚 Terminé\n{eq1} {score} {eq2}"
                            penalty_text = get_penalty_shootout_score(driver, url)
                            if penalty_text: msg += f"\n{penalty_text}"
                            
                            stats = get_match_stats(driver, get_stat_url(url))
                            broadcast_to_facebook(active_pages, f"{msg}\n\n{stats}".strip(), encryption_service)
                            
                            previously_published_ids.add(match_id)
                        except Exception as e: print(f"❌ Erreur sur traitement match terminé {match_id}: {e}")
            
            save_to_json(list(previously_published_ids), PUBLISHED_FINISHED_FILE)
            
        except Exception as e:
            print(f"ERREUR MAJEURE dans run_centralized_checks: {e}")
        finally:
            driver.quit()
            duration = time.time() - start_time
            print(f"--- Cycle centralisé terminé en {duration:.2f} secondes ---")



# Dans app/tasks.py

# Dans app/tasks.py

def publish_news_for_business_users():
    """
    Tâche qui scrape les actualités et les publie UNIQUEMENT pour les abonnés Business.
    Enregistre les publications dans l'historique unifié (table Broadcast).
    """
    if _app is None: return
    with _app.app_context():
        start_time = time.time()
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Démarrage de la publication des actualités ---")

        # 1. On récupère UNIQUEMENT les pages des abonnés "Business" actifs
        business_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(
                User.role == 'superadmin', # Le superadmin reçoit aussi les actus
                User.subscription_plan == 'business'
            )
        ).all()

        if not business_pages:
            print("Aucun abonné Business actif. Tâche terminée.")
            return

        print(f"Ciblage de {len(business_pages)} page(s) pour la publication des actualités.")
        encryption_service = EncryptionService()
        driver = get_browser()
        if not driver: return

        try:
            # 2. On scrape les dernières news avec leur contenu complet
            latest_news = scrape_football_news(driver)
            if not latest_news:
                return

            # 3. On récupère les URL des news déjà publiées pour éviter les doublons
            published_urls = {news.article_url for news in PublishedNews.query.all()}

            # 4. On filtre pour ne garder que les nouvelles actualités
            news_to_publish = []
            for news in reversed(latest_news): # On inverse pour publier les plus anciennes en premier
                if news['url'] not in published_urls:
                    news_to_publish.append(news)
            
            if news_to_publish:
                print(f"-> {len(news_to_publish)} nouvelle(s) actualité(s) à publier :")
                for news in news_to_publish:
                    print(f"   - TITRE: {news['title']}")
            else:
                print("Aucune nouvelle actualité à publier.")
            
            for news in news_to_publish:
                # 5. On construit le message final, sans la source
                message = f"🚨 **ACTU FOOT** 🚨\n\n**{news['title']}**\n\n{news['content']}"
                
                # 6. On utilise broadcast_to_facebook. Cette fonction va :
                #    a) Enregistrer le message dans la table 'Broadcast'
                #    b) Publier le message sur toutes les pages 'business_pages'
                broadcast_to_facebook(business_pages, message, encryption_service)
                
                # 7. On enregistre la news dans la table de contrôle 'PublishedNews' 
                #    pour s'assurer qu'elle ne sera plus jamais traitée.
                #    On n'a plus besoin de stocker le contenu ici.
                new_published_news = PublishedNews(article_url=news['url'], title=news['title'])
                db.session.add(new_published_news)
                db.session.commit()
                
                # Petite pause pour ne pas surcharger l'API de Facebook
                time.sleep(10)

        finally:
            driver.quit()
            duration = time.time() - start_time
            print(f"--- Publication des actualités terminée en {duration:.2f} secondes ---")


# =============================================================================
# === ENREGISTREMENT DES TÂCHES ===============================================
# =============================================================================

if scheduler.get_job('centralized_checks_job'):
    scheduler.remove_job('centralized_checks_job')
if scheduler.get_job('summary_post_job'): # Supprime l'ancienne tâche de résumé si elle existe
    scheduler.remove_job('summary_post_job')
if scheduler.get_job('main_scraping_job'): # Supprime l'ancienne tâche si elle existe
    scheduler.remove_job('main_scraping_job')


scheduler.add_job(
    id='centralized_checks_job', 
    func=run_centralized_checks, 
    trigger='interval', 
    minutes=2,
    replace_existing=True
)

# À la fin de app/tasks.py, dans la section d'enregistrement

if not scheduler.get_job('check_expired_job'):
    scheduler.add_job(
        id='check_expired_job',
        func=check_expired_subscriptions,
        trigger='cron', # Se déclenche à une heure précise
        hour=1, # Tous les jours à 1h du matin (heure du serveur)
        minute=5
    )
    
    

# ... (l'enregistrement de centralized_checks_job) ...

if not scheduler.get_job('publish_news_job'):
    scheduler.add_job(
        id='publish_news_job', 
        func=publish_news_for_business_users, 
        trigger='interval', 
        minutes=15 # Par exemple, toutes les 15 minutes
    )
    
    
if not scheduler.get_job('live_summary_job'):
    scheduler.add_job(
        id='live_summary_job', 
        func=post_live_scores_summary, 
        trigger='interval', 
        minutes=30
>>>>>>> fbb69e9e5633005d19d8e9365d836fbf1f87dd2a
    )