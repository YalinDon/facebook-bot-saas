# app/tasks.py (Version Finale de Production - 100% BDD et Logique Corrigée)

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
import threading
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
# === FONCTIONS UTILITAIRES ===================================================
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
    options.add_argument('--disable-cache')
    try:
        service = Service() 
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(60)
        return driver
    except Exception as e:
        print(f"[ERREUR SELENIUM] Impossible de démarrer le navigateur : {e}")
        return None

def broadcast_to_facebook(active_pages, message):
    try:
        db.session.add(Broadcast(content=message))
        db.session.commit()
        print(f"[HISTORIQUE] Message enregistré: {message[:60]}...")
    except Exception as e:
        db.session.rollback()
        _app.logger.error(f"[HISTORIQUE ERREUR] {e}")
    if not active_pages:
        print(f"[BROADCAST IGNORÉ] Aucun auditeur actif.")
        return
    print(f"[BROADCAST] Envoi à {len(active_pages)} page(s)...")
    encryption_service = EncryptionService()
    for page in active_pages:
        try:
            graph = GraphAPI(access_token=encryption_service.decrypt(page.encrypted_page_access_token))
            graph.put_object(parent_object=page.facebook_page_id, connection_name="feed", message=message)
            print(f"  -> Succès pour '{page.page_name}'")
        except Exception as e:
            print(f"  -> ERREUR FB pour '{page.page_name}': {e}")

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
        for row in reversed(soup.select("tr")):
            if row.select_one("span.st1.eventTypeG"):
                buteur = row.select_one("span.st1.eventTypeG").text.strip()
                minute = row.select_one("td.c2").text.strip()
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
        stats, seen_titles = [], set()
        for block in soup.select("div.progressBar"):
            titre_el, v1_el, v2_el = block.select_one("h5.progressHeaderTitle"), block.select_one("span.progressBarValue1"), block.select_one("span.progressBarValue2")
            if titre_el and v1_el and v2_el and (titre_text := titre_el.text.strip()) not in seen_titles:
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
        penalty_cell = BeautifulSoup(driver.page_source, "html.parser").find("td", string=lambda text: "Penalties" in text if text else False)
        if penalty_cell and (score_tag := penalty_cell.find("b")):
            return f"Tirs au but : {score_tag.text.strip()}"
    except Exception: pass
    return None

def get_article_content(driver, article_url):
    try:
        driver.get(article_url)
        content = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#cont12 p.par1"))).get_attribute('innerText').strip()
        return content[:1500] + "..." if len(content) > 1500 else content
    except Exception as e:
        print(f"   -> Avertissement: Impossible de scraper le contenu de {article_url}. Erreur: {e}")
        return None

def scrape_football_news(driver):
    print("📰 Scraping des actualités...")
    news_list = []
    try:
        driver.get("https://www.maxifoot.fr/")
        try:
            WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button"))).click()
            time.sleep(1)
        except TimeoutException: pass

        container = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.listegen5.listeInfo3")))
        for link_tag in BeautifulSoup(container.get_attribute('outerHTML'), "html.parser").find_all("a", href=True):
            if "Voir les brèves précédentes" in link_tag.get_text(): continue
            if (time_tag := link_tag.find('b')): time_tag.extract()
            title = link_tag.get_text(strip=True)
            url = link_tag['href']
            if not url.startswith('http'): url = "https://news.maxifoot.fr/" + url.lstrip('/')
            if (content := get_article_content(driver, url)):
                news_list.append({'title': title, 'url': url, 'content': content})
        print(f"✅ {len(news_list)} actualités avec contenu trouvées.")
    except Exception as e: print(f"[ERREUR SCRAPING NEWS] {e}")
    return news_list

# =============================================================================
# === TÂCHES PLANIFIÉES =======================================================
# =============================================================================

def run_centralized_checks():
    if _app is None: return
    with _app.app_context():
        start_time = time.time()
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Démarrage du cycle de vérification des scores ---")
        
        active_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(User.role == 'superadmin', User.subscription_status == 'active', User.trial_ends_at > datetime.utcnow())
        ).all()
        if not active_pages: print("Aucune page éligible pour la publication.")

        driver = get_browser()
        if not driver: return

        try:
            old_scores_from_db = GlobalMatchState.query.all()
            old_scores = {s.match_key: s for s in old_scores_from_db}
            new_scores_data = get_live_scores(driver)
            
            for match_key, new_data in new_scores_data.items():
                old_state = old_scores.get(match_key)
                if not old_state:
                    if new_data['score'].replace(" ","") != "-" and "'" in new_data['minute']:
                        broadcast_to_facebook(active_pages, f"⏱️ {new_data['minute']}\n{new_data['eq1']} {new_data['score']} {new_data['eq2']}")
                    continue

                if new_data['statut'] == "MT" and old_state.statut != "MT":
                    msg = f"⏸️ Mi-temps\n{new_data['eq1']} {new_data['score']} {new_data['eq2']}"
                    stats = get_match_stats(driver, get_stat_url(new_data['url']))
                    broadcast_to_facebook(active_pages, f"{msg}\n\n{stats}".strip())
                elif new_data['score'] != old_state.score:
                    try:
                        s1_old, s2_old = map(int, old_state.score.replace(" ","").split("-"))
                        s1_new, s2_new = map(int, new_data['score'].replace(" ","").split("-"))
                        if s1_new > s1_old or s2_new > s2_old:
                            equipe_but = new_data['eq1'] if s1_new > s1_old else new_data['eq2']
                            buteur, minute_but = get_match_details(driver, new_data['url'])
                            minute_affiche = minute_but or new_data['minute']
                            msg_buteur = f"🚀 Buuuut de {equipe_but} !"
                            if buteur:
                                if buteur.startswith('('): pass
                                elif '(' in buteur: msg_buteur = f"🚀 Buuuut de {buteur.split('(')[0].strip()} 🔥 ({equipe_but}) !"
                                else: msg_buteur = f"🚀 Buuuut de {buteur} ({equipe_but}) !"
                            broadcast_to_facebook(active_pages, f"{msg_buteur}\n⏱️ {minute_affiche}\n{new_data['eq1']} {new_data['score']} {new_data['eq2']}")
                        elif s1_new < s1_old or s2_new < s2_old:
                            broadcast_to_facebook(active_pages, f"❌ BUT REFUSÉ...\n\nLe score revient à {new_data['eq1']} {new_data['score']} {new_data['eq2']}")
                    except (ValueError, IndexError): continue
            
            # Mise à jour BDD scores
            current_keys = set(new_scores_data.keys())
            for state in old_scores_from_db:
                if state.match_key not in current_keys: db.session.delete(state)
            for match_key, data in new_scores_data.items():
                state = old_scores.get(match_key)
                if state: state.score, state.statut, state.minute, state.url, state.eq1, state.eq2 = data['score'], data['statut'], data['minute'], data['url'], data['eq1'], data['eq2']
                else: db.session.add(GlobalMatchState(match_key=match_key, **data))
            db.session.commit()

            # Traitement des matchs terminés
            previously_published_ids = {p.match_identifier for p in GlobalPublishedMatch.query.all()}
            driver.get(FINISHED_URL)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tr[data-matchid]")))
            for row in BeautifulSoup(driver.page_source, "html.parser").select("tr[data-matchid]"):
                if "TER" in (row.select_one("td.lm2").text or "") and (match_id := row['data-matchid']) not in previously_published_ids:
                    try:
                        eq1, eq2, score = row.select_one("span.lm3_eq1").text.strip(), row.select_one("span.lm3_eq2").text.strip(), row.select_one("span.lm3_score").text.strip()
                        url = f"https://www.matchendirect.fr{row.select_one('a.ga4-matchdetail').get('href')}"
                        msg = f"🔚 Terminé\n{eq1} {score} {eq2}"
                        if (penalty_text := get_penalty_shootout_score(driver, url)): msg += f"\n{penalty_text}"
                        stats = get_match_stats(driver, get_stat_url(url))
                        broadcast_to_facebook(active_pages, f"{msg}\n\n{stats}".strip())
                        db.session.add(GlobalPublishedMatch(match_identifier=match_id))
                        db.session.commit()
                    except Exception as e: 
                        print(f"❌ Erreur match terminé {match_id}: {e}"); db.session.rollback()
        except Exception as e:
            print(f"ERREUR MAJEURE dans run_centralized_checks: {e}"); db.session.rollback()
        finally:
            driver.quit()
            print(f"--- Cycle scores terminé en {time.time() - start_time:.2f}s ---")

def post_live_scores_summary():
    if _app is None: return
    with _app.app_context():
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Démarrage du résumé des scores ---")
        scores_from_db = GlobalMatchState.query.all()
        current_summary_list = sorted([f"{s.match_key}:{s.score}" for s in scores_from_db if s.statut != "TER"])
        if not current_summary_list:
            print("Aucun match en cours à résumer."); return

        current_hash = hashlib.md5("|".join(current_summary_list).encode('utf-8')).hexdigest()
        last_hash_obj = GlobalState.query.filter_by(key='last_summary_hash').first()
        last_hash = last_hash_obj.value if last_hash_obj else ''

        if current_hash == last_hash:
            print("Résumé des scores inchangé, aucune publication."); return
        
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
        print("--- Publication du résumé terminée ---")

def check_expired_subscriptions():
    if _app is None: return
    with _app.app_context():
        now = datetime.utcnow()
        expired_users = User.query.filter(User.subscription_status == 'active', User.subscription_expires_at != None, User.subscription_expires_at < now).all()
        if not expired_users: return
        for user in expired_users:
            user.subscription_status = 'inactive'
            user.subscription_plan = None
        db.session.commit()

def publish_news_for_business_users():
    if _app is None: return
    with _app.app_context():
        start_time = time.time()
        print(f"\n--- Publication des actualités ---")
        business_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            db.or_(User.role == 'superadmin', User.subscription_plan == 'business')
        ).all()
        if not business_pages: print("Aucun abonné Business actif."); return

        driver = get_browser()
        if not driver: return

        try:
            latest_news = scrape_football_news(driver)
            if not latest_news: return

            published_urls = {news.article_url for news in PublishedNews.query.all()}
            news_to_publish = [news for news in reversed(latest_news) if news['url'] not in published_urls]
            
            for news in news_to_publish:
                message = f"🚨 **ACTU FOOT** 🚨\n\n**{news['title']}**\n\n{news['content']}"
                broadcast_to_facebook(business_pages, message)
                db.session.add(PublishedNews(article_url=news['url'], title=news['title'], content=news['content']))
                db.session.commit()
                time.sleep(10)
        finally:
            driver.quit()
            print(f"--- Publication des actualités terminée en {time.time() - start_time:.2f}s ---")

def charge_with_fedapay_token(user, plan_info):
    api_base_url = _app.config['FEDAPAY_API_BASE']
    api_key = _app.config['FEDAPAY_SECRET_KEY']
    url = f"{api_base_url}/transactions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"description": f"Renouvellement abonnement - Forfait {plan_info['plan_name'].capitalize()}", "amount": plan_info['amount'], "currency": {"iso": "XOF"}, "token": user.fedapay_token}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()['v1/transaction']['status'] == 'approved'
    except Exception as e:
        print(f"ERREUR de renouvellement Fedapay pour {user.email}: {e}")
        return False

def run_daily_renewals():
    if _app is None: return
    with _app.app_context():
        print(f"\n--- Démarrage des renouvellements Fedapay ---")
        today = date.today()
        users_to_renew = User.query.filter(User.subscription_provider == 'fedapay', User.next_billing_date == today).all()
        if not users_to_renew: print("Aucun renouvellement Fedapay aujourd'hui."); return

        for user in users_to_renew:
            plan_id_to_renew = user.subscription_plan # Utilise le plan complet stocké, ex: 'pro_annual'
            plan_info = FEDAPAY_PLANS.get(plan_id_to_renew)

            if not plan_info or not user.fedapay_token:
                user.subscription_status = 'inactive'
                continue

            if charge_with_fedapay_token(user, plan_info):
                duration = plan_info['duration_days']
                user.next_billing_date = today + timedelta(days=duration)
            else:
                user.subscription_status, user.subscription_plan, user.next_billing_date = 'inactive', None, None
        db.session.commit()
        print("--- Renouvellements Fedapay terminés ---")



def start_realtime_match_monitor():
    """Scraping continu en arrière-plan pour une publication instantanée."""
    def loop():
        driver = get_browser()
        if not driver:
            print("[ERREUR] Impossible de démarrer le navigateur pour le moniteur temps réel.")
            return

        last_scores = {}
        while True:
            try:
                new_scores = get_live_scores(driver)
                for key, data in new_scores.items():
                    old = last_scores.get(key)
                    if not old:
                        last_scores[key] = data
                        continue
                    if data["score"] != old["score"]:
                        print(f"⚡ Détection immédiate : {key} → {data['score']}")
                        with _app.app_context():
                            active_pages = db.session.query(FacebookPage).join(User).filter(
                                FacebookPage.is_active == True,
                                db.or_(
                                    User.role == 'superadmin',
                                    User.subscription_status == 'active',
                                    User.trial_ends_at > datetime.utcnow()
                                )
                            ).all()
                            msg = f"⚽ But en direct !\n{data['eq1']} {data['score']} {data['eq2']}"
                            broadcast_to_facebook(active_pages, msg)
                    last_scores[key] = data
            except Exception as e:
                print(f"[MONITEUR ERREUR] {e}")
            time.sleep(8)  # 🔥 publication presque en temps réel
    threading.Thread(target=loop, daemon=True).start()

# Lancement du moniteur temps réel
start_realtime_match_monitor()

# =============================================================================
# === ENREGISTREMENT DES TÂCHES ===============================================
# =============================================================================

scheduler.add_job(id='centralized_checks_job', func=run_centralized_checks, trigger='interval', seconds=45, replace_existing=True)
scheduler.add_job(id='check_expired_job', func=check_expired_subscriptions, trigger='cron', hour=1, minute=5, replace_existing=True)
scheduler.add_job(id='publish_news_job', func=publish_news_for_business_users, trigger='interval', minutes=15, replace_existing=True)
scheduler.add_job(id='live_summary_job', func=post_live_scores_summary, trigger='interval', minutes=30, replace_existing=True)
scheduler.add_job(id='fedapay_renewal_job', func=run_daily_renewals, trigger='cron', hour=2, replace_existing=True)