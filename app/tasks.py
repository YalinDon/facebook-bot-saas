# app/tasks.py (Version Finale - Base de Données)

import time, hashlib, requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from facebook import GraphAPI

from app import scheduler, db
from app.models import User, FacebookPage, Broadcast, PublishedNews, GlobalMatchState, GlobalPublishedMatch, GlobalState
from app.services import EncryptionService
from app.plans import FEDAPAY_PLANS

# --- Config ---
_app = None
LIVE_URL = "https://www.matchendirect.fr/live-score/"
FINISHED_URL = "https://www.matchendirect.fr/live-foot/"

def init_app(app):
    global _app
    _app = app

# =============================================================================
# === FONCTIONS UTILITAIRES DE SCRAPING =======================================
# =============================================================================

def get_browser():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-popup-blocking')
    try:
        service = Service() 
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(60)
        return driver
    except Exception as e:
        print(f"[ERREUR SELENIUM] Impossible de démarrer le navigateur : {e}")
        return None




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
        for match in soup.select("td.lm3"):
            try:
                eq1, eq2 = match.select_one("span.lm3_eq1").text.strip(), match.select_one("span.lm3_eq2").text.strip()
                score1, score2 = match.select_one("span.scored_1").text.strip(), match.select_one("span.scored_2").text.strip()
                row = match.find_parent("tr")
                minute = row.select_one("td.lm2").text.strip() if row.select_one("td.lm2") else ""
                url = f"https://www.matchendirect.fr{row.select_one('a').get('href')}" if row.select_one('a') else None
                statut = "MT" if "mi-temps" in minute.lower() else ("TER" if "ter" in minute.lower() else "")
                scores[f"{eq1} vs {eq2}"] = {"score": f"{score1.strip()} - {score2.strip()}", "statut": statut, "minute": minute, "eq1": eq1, "eq2": eq2, "url": url}
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


def broadcast_to_facebook(active_pages, message):
    try:
        db.session.add(Broadcast(content=message))
        db.session.commit()
        print(f"[HISTORIQUE] Message enregistré: {message[:60]}...")
    except Exception as e:
        db.session.rollback()
        _app.logger.error(f"[HISTORIQUE ERREUR] {e}")
    if not active_pages: return
    print(f"[BROADCAST] Envoi à {len(active_pages)} page(s)...")
    encryption_service = EncryptionService()
    for page in active_pages:
        try:
            graph = GraphAPI(access_token=encryption_service.decrypt(page.encrypted_page_access_token))
            graph.put_object(parent_object=page.facebook_page_id, connection_name="feed", message=message)
            print(f"  -> Succès pour '{page.page_name}'")
        except Exception as e:
            print(f"  -> ERREUR FB pour '{page.page_name}': {e}")
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

# --- FONCTION DE RÉSUMÉ CORRIGÉE ---
def post_live_scores_summary():
    if _app is None: return
    with _app.app_context():
        scores_from_db = GlobalMatchState.query.all()
        current_summary_list = sorted([f"{s.match_key}:{s.score}" for s in scores_from_db if s.statut != "TER"])
        if not current_summary_list: return

        current_hash = hashlib.md5("|".join(current_summary_list).encode('utf-8')).hexdigest()
        last_hash_obj = GlobalState.query.filter_by(key='last_summary_hash').first()
        last_hash = last_hash_obj.value if last_hash_obj else ''

        if current_hash == last_hash:
            print("Résumé scores inchangé.")
            return
        
        active_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(User.role == 'superadmin', User.subscription_status == 'active', User.trial_ends_at > datetime.utcnow())
        ).all()
        if not active_pages: return

        message = "📊 Scores en direct :\n\n"
        for s in sorted(scores_from_db, key=lambda x: x.match_key):
            if s.statut != "TER":
                ligne = f"{s.eq1} {s.score} {s.eq2}"
                if s.statut == "MT": ligne += " (MT)"
                elif "'" in s.minute: ligne += f" ({s.minute})"
                message += f"◉ {ligne}\n"
        
        broadcast_to_facebook(active_pages, message.strip())

        if last_hash_obj: last_hash_obj.value = current_hash
        else: db.session.add(GlobalState(key='last_summary_hash', value=current_hash))
        db.session.commit()



# Dans app/tasks.py

def run_centralized_checks():
    """
    Tâche principale qui scrape les scores en direct et les matchs terminés,
    compare l'état avec la base de données, et diffuse les changements.
    """
    if _app is None: return
    with _app.app_context():
        start_time = time.time()
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Démarrage du cycle de vérification des scores ---")
        
        active_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(User.role == 'superadmin', User.subscription_status == 'active', User.trial_ends_at > datetime.utcnow())
        ).all()

        if not active_pages:
            print("Aucune page active ou en période d'essai pour la publication.")
        else:
            print(f"{len(active_pages)} page(s) éligibles pour la publication.")

        driver = get_browser()
        if not driver: return

        try:
            # --- 1. TRAITEMENT DES MATCHS EN DIRECT ---
            old_scores_from_db = GlobalMatchState.query.all()
            old_scores = {s.match_key: s for s in old_scores_from_db}
            new_scores_data = get_live_scores(driver)
            
            for match_key, new_data in new_scores_data.items():
                old_state = old_scores.get(match_key)
                
                if not old_state:
                    if new_data['score'].replace(" ","") != "-" and "'" in new_data['minute']:
                        message = f"⏱️ {new_data['minute']}\n{new_data['eq1']} {new_data['score']} {new_data['eq2']}"
                        broadcast_to_facebook(active_pages, message)
                    continue

                changement_score = new_data['score'] != old_state.score
                changement_statut_mt = new_data['statut'] == "MT" and old_state.statut != "MT"

                if changement_statut_mt:
                    msg = f"⏸️ Mi-temps\n{new_data['eq1']} {new_data['score']} {new_data['eq2']}"
                    stats = get_match_stats(driver, get_stat_url(new_data['url']))
                    broadcast_to_facebook(active_pages, f"{msg}\n\n{stats}".strip())

                elif changement_score:
                    try:
                        if not old_state.score or "-" not in old_state.score or "-" not in new_data['score']: continue
                        s1_old, s2_old = map(int, old_state.score.replace(" ","").split("-"))
                        s1_new, s2_new = map(int, new_data['score'].replace(" ","").split("-"))

                        if s1_new > s1_old or s2_new > s2_old:
                            equipe_but = new_data['eq1'] if s1_new > s1_old else new_data['eq2']
                            buteur_brut, minute_but = get_match_details(driver, new_data['url'])
                            minute_affiche = minute_but if minute_but else new_data['minute']
                            msg_buteur = ""
                            if buteur_brut:
                                if buteur_brut.startswith('('): msg_buteur = f"🚀 Buuuut de {equipe_but} !"
                                elif '(' in buteur_brut:
                                    nom_propre = f"{buteur_brut.split('(')[0].strip()} 🔥"
                                    msg_buteur = f"🚀 Buuuut de {nom_propre} ({equipe_but}) !"
                                else: msg_buteur = f"🚀 Buuuut de {buteur_brut} ({equipe_but}) !"
                            else: msg_buteur = f"🚀 Buuuut de {equipe_but} !"
                            broadcast_to_facebook(active_pages, f"{msg_buteur}\n⏱️ {minute_affiche}\n{new_data['eq1']} {new_data['score']} {new_data['eq2']}")
                        
                        elif s1_new < s1_old or s2_new < s2_old:
                            equipe_concernee = new_data['eq1'] if s1_new < s1_old else new_data['eq2']
                            msg = f"❌ BUT REFUSÉ pour {equipe_concernee} après consultation de la VAR.\n\nLe score revient à {new_data['eq1']} {new_data['score']} {new_data['eq2']}"
                            broadcast_to_facebook(active_pages, msg)
                    except (ValueError, IndexError): continue
            
            # Mise à jour de la BDD pour les scores en direct
            current_keys = set(new_scores_data.keys())
            for state in old_scores_from_db:
                if state.match_key not in current_keys: db.session.delete(state)
            for match_key, data in new_scores_data.items():
                state = old_scores.get(match_key)
                if state:
                    state.score, state.statut, state.minute, state.url, state.eq1, state.eq2 = data['score'], data['statut'], data['minute'], data['url'], data['eq1'], data['eq2']
                else:
                    db.session.add(GlobalMatchState(match_key=match_key, **data))
            db.session.commit()

            # --- 2. TRAITEMENT DES MATCHS TERMINÉS ---
            previously_published_ids = {p.match_identifier for p in GlobalPublishedMatch.query.all()}
            driver.get(FINISHED_URL)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tr[data-matchid]")))
            soup = BeautifulSoup(driver.page_source, "html.parser")
            
            for row in soup.select("tr[data-matchid]"):
                if "TER" in (row.select_one("td.lm2").text or ""):
                    match_id = row['data-matchid']
                    if match_id not in previously_published_ids:
                        try:
                            eq1 = row.select_one("span.lm3_eq1").text.strip()
                            eq2 = row.select_one("span.lm3_eq2").text.strip()
                            score = row.select_one("span.lm3_score").text.strip()
                            url = f"https://www.matchendirect.fr{row.select_one('a.ga4-matchdetail').get('href')}"
                            
                            print(f"✨ Nouveau match terminé détecté: {eq1} vs {eq2}")
                            msg = f"🔚 Terminé\n{eq1} {score} {eq2}"
                            
                            penalty_text = get_penalty_shootout_score(driver, url)
                            if penalty_text: msg += f"\n{penalty_text}"
                            
                            stats = get_match_stats(driver, get_stat_url(url))
                            full_message = f"{msg}\n\n{stats}".strip()
                            
                            broadcast_to_facebook(active_pages, full_message)
                            
                            db.session.add(GlobalPublishedMatch(match_identifier=match_id))
                            db.session.commit()
                        except Exception as e: 
                            print(f"❌ Erreur sur traitement du match terminé {match_id}: {e}")
                            db.session.rollback()
        
        except Exception as e:
            print(f"ERREUR MAJEURE dans run_centralized_checks: {e}")
            db.session.rollback()
        finally:
            driver.quit()
            duration = time.time() - start_time
            print(f"--- Cycle des scores terminé en {duration:.2f} secondes ---")


def charge_with_fedapay_token(user, plan_info):
    """Tente de prélever un utilisateur avec un token Fedapay."""
    api_base_url = _app.config['FEDAPAY_API_BASE']
    api_key = _app.config['FEDAPAY_SECRET_KEY']
    url = f"{api_base_url}/transactions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    data = {
        "description": f"Renouvellement abonnement - Forfait {plan_info['plan_name'].capitalize()}",
        "amount": plan_info['amount'],
        "currency": {"iso": "XOF"},
        "token": user.fedapay_token
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        res_data = response.json()
        return res_data['v1/transaction']['status'] == 'approved'
    except Exception as e:
        print(f"ERREUR de renouvellement Fedapay pour {user.email}: {e}")
        return False

# Dans app/tasks.py

def run_daily_renewals():
    """Tâche nocturne qui gère les renouvellements d'abonnement Fedapay."""
    if _app is None: return
    with _app.app_context():
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d')}] Démarrage des renouvellements Fedapay ---")
        
        today = date.today()
        users_to_renew = User.query.filter(
            User.subscription_provider == 'fedapay',
            User.next_billing_date == today
        ).all()

        if not users_to_renew:
            print("Aucun renouvellement Fedapay prévu aujourd'hui.")
            return

        print(f"Trouvé {len(users_to_renew)} utilisateur(s) à renouveler...")
        for user in users_to_renew:
            # --- DÉBUT DE LA LOGIQUE CORRIGÉE ---
            # On trouve le plan correspondant au renouvellement. On assume qu'ils renouvellent
            # avec la même durée. On doit deviner si c'est mensuel ou annuel.
            # NOTE: Il faudrait stocker la durée pour que ce soit parfait.
            # Pour l'instant, on cherche le plan mensuel correspondant.
            plan_id_to_renew = user.subscription_plan
            plan_info = FEDAPAY_PLANS.get(plan_id_to_renew)

            if not plan_info or not user.fedapay_token:
                print(f"Données de renouvellement invalides pour {user.email}, annulation.")
                user.subscription_status = 'inactive'
                continue
            # --- FIN DE LA LOGIQUE CORRIGÉE ---

            if charge_with_fedapay_token(user, plan_info):
                duration = plan_info['duration_days']
                user.next_billing_date = today + timedelta(days=duration)
                print(f" -> Renouvellement RÉUSSI pour {user.email}")
            else:
                user.subscription_status = 'inactive'
                user.subscription_plan = None
                user.next_billing_date = None
                print(f" -> Renouvellement ÉCHOUÉ pour {user.email}. Compte désactivé.")

        db.session.commit()
        print("--- Renouvellements Fedapay terminés ---")

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
                broadcast_to_facebook(business_pages, message)
                
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
    seconds=45,
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
    )
    
if not scheduler.get_job('fedapay_renewal_job'):
    scheduler.add_job(
        id='fedapay_renewal_job',
        func=run_daily_renewals,
        trigger='cron',
        hour=2 # Tous les jours à 2h du matin
    )
    