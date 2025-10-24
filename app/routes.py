# app/routes.py

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    current_app, session
)
from flask_login import login_user, logout_user, current_user, login_required
from datetime import datetime, timedelta
from app import tasks
# Correction des imports pour éviter les duplications
from . import db
from .forms import LoginForm, RegistrationForm, RequestResetForm, ResetPasswordForm
from .models import User, FacebookPage, Broadcast, Notification, PublishedNews
from .services import EncryptionService
from .utils import send_reset_email, is_valid_fedapay_signature
import facebook
import stripe
import requests
from flask_babel import _
# Dans app/routes.py, après les imports
from functools import wraps
from .plans import FEDAPAY_PLANS
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Un admin normal OU un superadmin peuvent accéder
        if not (current_user.role == 'admin' or current_user.is_superadmin):
            flash("Accès non autorisé.", "danger")
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function
# --- MAPPING DES FORFAITS ---

main = Blueprint('main', __name__)

# =============================================================================
# === ROUTES D'AUTHENTIFICATION ET DE BASE ====================================
# =============================================================================

@main.route('/')
def index(): return render_template('index.html')

@main.route('/register', methods=['GET', 'POST'])
def register():
    # ... (inchangé)
    if current_user.is_authenticated: return redirect(url_for('main.dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Votre compte a été créé ! Vous pouvez maintenant vous connecter.', 'success')
        return redirect(url_for('main.login'))
    return render_template('register.html', title='Inscription', form=form)

@main.route('/login', methods=['GET', 'POST'])
def login():
    # ... (inchangé)
    if current_user.is_authenticated: return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash('Connexion réussie !', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('main.dashboard'))
        else:
            flash('Échec de la connexion. Vérifiez email et mot de passe.', 'danger')
    return render_template('login.html', title='Connexion', form=form)

@main.route('/logout')
def logout():
    # ... (inchangé)
    logout_user()
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('main.index'))

@main.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    # ... (inchangé)
    if current_user.is_authenticated: return redirect(url_for('main.dashboard'))
    form = RequestResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user: send_reset_email(user)
        flash('Si un compte avec cet email existe, un email de réinitialisation a été envoyé.', 'info')
        return redirect(url_for('main.login'))
    return render_template('reset_request.html', title='Mot de passe oublié', form=form)

@main.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    # ... (inchangé)
    if current_user.is_authenticated: return redirect(url_for('main.dashboard'))
    user = User.verify_reset_token(token)
    if user is None:
        flash('Le jeton de réinitialisation est invalide ou a expiré.', 'warning')
        return redirect(url_for('main.reset_request'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Votre mot de passe a été mis à jour ! Vous pouvez maintenant vous connecter.', 'success')
        return redirect(url_for('main.login'))
    return render_template('reset_token.html', title='Réinitialiser le mot de passe', form=form)

# Dans app/routes.py

# ... (Assurez-vous que tous les imports nécessaires sont en haut du fichier)
# from .models import User, FacebookPage, Broadcast, PublishedNews

# Dans app/routes.py

# Dans app/routes.py

@main.route('/dashboard')
@login_required
def dashboard():
    pages = FacebookPage.query.filter_by(user_id=current_user.id).all()
    
    # --- DÉBUT DE LA LOGIQUE D'HISTORIQUE UNIFIÉ ---
    
    # 1. On récupère les publications de scores
    score_broadcasts = Broadcast.query.order_by(Broadcast.timestamp.desc()).limit(15).all()
    
    # 2. On initialise une liste vide pour l'historique final
    history_items = []

    # 3. On ajoute les scores à la liste, en leur donnant un type
    for item in score_broadcasts:
        history_items.append({
            'type': 'score',
            'timestamp': item.timestamp,
            'content': item.content
        })

    # 4. Si l'utilisateur est un abonné Business, on ajoute les actualités
    if current_user.subscription_status == 'active' and current_user.subscription_plan == 'business':
        business_news = PublishedNews.query.order_by(PublishedNews.published_at.desc()).limit(15).all()
        for item in business_news:
            history_items.append({
                'type': 'news',
                'timestamp': item.published_at,
                'title': item.title,
                'content': item.content,
                'url': item.article_url
            })
    
    # 5. On trie la liste combinée par date, du plus récent au plus ancien
    history_items.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # --- FIN DE LA LOGIQUE D'HISTORIQUE UNIFIÉ ---
        
    return render_template(
        'dashboard.html', 
        title='Tableau de bord', 
        pages=pages, 
        history_items=history_items[:15] # On renvoie une seule liste triée de 15 éléments max
    )

# =============================================================================
# === ROUTES DE GESTION (FACEBOOK, ESSAI, PAIEMENT) ===========================
# =============================================================================

# --- ROUTE MODIFIÉE ---
@main.route('/facebook_login')
@login_required
def facebook_login():
    if not current_user.is_superadmin:
        now = datetime.utcnow()
        is_in_trial = current_user.trial_ends_at is not None and current_user.trial_ends_at > now
        page_count = FacebookPage.query.filter_by(user_id=current_user.id).count()

        # Application des limites de pages
        if current_user.subscription_status != 'active':
            if is_in_trial and page_count >= 1:
                flash("Votre période d'essai est limitée à 1 page.", "warning")
                return redirect(url_for('main.dashboard'))
        elif current_user.subscription_plan == 'pro' and page_count >= 3:
            flash("Votre forfait 'Pro' est limité à 3 pages.", "warning")
            return redirect(url_for('main.dashboard'))
    
    # Le reste est inchangé
    facebook_redirect_uri = url_for('main.facebook_callback', _external=True)
    permissions = ['pages_show_list', 'pages_manage_posts', 'pages_read_engagement']
    dialog_url = (f"https://www.facebook.com/dialog/oauth?client_id={current_app.config['FACEBOOK_APP_ID']}&redirect_uri={facebook_redirect_uri}&scope={','.join(permissions)}")
    return redirect(dialog_url)



@main.route('/facebook/callback')
@login_required
def facebook_callback():
    # 1. Vérifie si Facebook a renvoyé une erreur directement dans l'URL
    error = request.args.get('error')
    if error:
        error_description = request.args.get('error_description', 'Aucune description fournie.')
        flash(f"Erreur d'autorisation de Facebook : {error_description}", "danger")
        current_app.logger.error(f"Erreur de callback Facebook : {error} - {error_description}")
        return redirect(url_for('main.dashboard'))

    # 2. Récupère le code d'autorisation
    auth_code = request.args.get('code')
    if not auth_code:
        flash("Code d'autorisation manquant dans la réponse de Facebook. Veuillez réessayer.", "danger")
        return redirect(url_for('main.dashboard'))
    
    facebook_redirect_uri = url_for('main.facebook_callback', _external=True)
    
    try:
        # Étape 1 : Échanger le code contre un token de courte durée
        graph = facebook.GraphAPI()
        token_response = graph.get_access_token_from_code(
            code=auth_code,
            redirect_uri=facebook_redirect_uri,
            app_id=current_app.config['FACEBOOK_APP_ID'],
            app_secret=current_app.config['FACEBOOK_APP_SECRET']
        )
        
        user_access_token = token_response.get('access_token')
        if not user_access_token:
            flash("Impossible de récupérer le token d'accès initial depuis Facebook.", "danger")
            return redirect(url_for('main.dashboard'))

        # Étape 2 : Échanger le token de courte durée contre un de longue durée
        graph_with_token = facebook.GraphAPI(access_token=user_access_token)
        long_lived_token_response = graph_with_token.extend_access_token(
            app_id=current_app.config['FACEBOOK_APP_ID'],
            app_secret=current_app.config['FACEBOOK_APP_SECRET']
        )
        
        long_lived_user_token = long_lived_token_response.get('access_token')
        if not long_lived_user_token:
            flash("Impossible de valider le token d'accès sur le long terme.", "danger")
            return redirect(url_for('main.dashboard'))

        # Étape 3 : Récupérer les pages de l'utilisateur avec le token final
        graph_final = facebook.GraphAPI(access_token=long_lived_user_token)
        pages_data = graph_final.get_connections(id='me', connection_name='accounts', fields='name,id,access_token')
        
        user_pages = [{'id': p['id'], 'name': p['name'], 'access_token': p['access_token']} for p in pages_data.get('data', [])]
        
        if not user_pages:
             flash("Aucune page Facebook n'a été trouvée. Assurez-vous d'avoir bien accordé les permissions nécessaires.", "warning")
             return redirect(url_for('main.dashboard'))

        # Si tout s'est bien passé, on stocke les pages et on redirige vers la sélection
        session['facebook_pages'] = user_pages
        return redirect(url_for('main.select_facebook_page'))

    except facebook.GraphAPIError as e:
        flash(f"Une erreur est survenue lors de la communication avec Facebook : {e}", "danger")
        current_app.logger.error(f"GraphAPIError dans le callback: {e}")
        return redirect(url_for('main.dashboard'))
    except Exception as e:
        flash("Une erreur système inattendue est survenue. Veuillez réessayer.", "danger")
        current_app.logger.error(f"Erreur inattendue dans le callback: {e}")
        return redirect(url_for('main.dashboard'))

# Dans app/routes.py

@main.route('/select_page', methods=['GET', 'POST'])
@login_required
def select_facebook_page():
    # 1. Vérification initiale : les pages existent-elles dans la session ?
    pages = session.get('facebook_pages')
    if not pages:
        # Pas besoin de message flash ici, car la redirection est immédiate
        # et une redirection depuis /facebook/callback afficherait déjà un message.
        return redirect(url_for('main.dashboard'))

    # 2. On ne traite la logique que si le formulaire est soumis
    if request.method == 'POST':
        choice_index_str = request.form.get('page_choice')

        # 3. Validation de l'entrée utilisateur : l'utilisateur a-t-il bien choisi une page ?
        if not choice_index_str:
            flash(_("Veuillez sélectionner une page."), "danger")
            return render_template('select_page.html', pages=pages)

        # 4. Vérification des limites de pages (uniquement pour les non-superadmins)
        if not current_user.is_superadmin:
            now = datetime.utcnow()
            is_in_trial = current_user.trial_ends_at is not None and current_user.trial_ends_at > now
            page_count = FacebookPage.query.filter_by(user_id=current_user.id).count()

            if current_user.subscription_status != 'active' and is_in_trial and page_count >= 1:
                flash(_("Limite d'essai (1 page) atteinte. Veuillez vous abonner pour en ajouter plus."), "danger")
                session.pop('facebook_pages', None) # On nettoie la session
                return redirect(url_for('main.dashboard'))
            elif current_user.subscription_plan == 'pro' and page_count >= 3:
                flash(_("Limite du forfait Pro (3 pages) atteinte."), "danger")
                session.pop('facebook_pages', None) # On nettoie la session
                return redirect(url_for('main.dashboard'))
        
        # 5. Si toutes les vérifications passent, on procède à l'enregistrement
        chosen_page = pages[int(choice_index_str)]
        existing_page = FacebookPage.query.filter_by(facebook_page_id=chosen_page['id']).first()

        if existing_page and existing_page.user_id == current_user.id:
            flash(_("Cette page est déjà connectée à votre compte."), "info")
        elif existing_page:
            flash(_("Cette page est déjà utilisée par un autre compte."), "danger")
        else:
            try:
                new_page = FacebookPage(
                    owner=current_user,
                    facebook_page_id=chosen_page['id'],
                    page_name=chosen_page['name'],
                    encrypted_page_access_token=EncryptionService().encrypt(chosen_page['access_token']),
                    is_active=True
                )
                db.session.add(new_page)
                db.session.commit()
                flash(_("La page '%(page_name)s' a été connectée avec succès !", page_name=chosen_page['name']), "success")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Erreur de sauvegarde de page: {e}")
                flash(_("Une erreur est survenue lors de l'enregistrement de la page."), "danger")
        
        # 6. Finalisation : on nettoie la session et on redirige
        session.pop('facebook_pages', None)
        return redirect(url_for('main.dashboard'))

    # 7. Si la méthode est GET, on affiche simplement la page de sélection
    return render_template('select_page.html', pages=pages)

@main.route('/page/<int:page_id>/toggle_active', methods=['POST'])
@login_required
def toggle_page_active(page_id):
    # ... (inchangé)
    page = FacebookPage.query.get_or_404(page_id)
    if page.owner != current_user: return redirect(url_for('main.dashboard'))
    page.is_active = not page.is_active
    db.session.commit()
    status = "activée" if page.is_active else "désactivée"
    flash(f"La page '{page.page_name}' a été {status}.", "success")
    return redirect(url_for('main.dashboard'))

@main.route('/page/<int:page_id>/delete', methods=['POST'])
@login_required
def delete_page(page_id):
    # ... (inchangé)
    page = FacebookPage.query.get_or_404(page_id)
    if page.owner != current_user: return redirect(url_for('main.dashboard'))
    db.session.delete(page)
    db.session.commit()
    flash(f"La page '{page.page_name}' a été supprimée.", "success")
    return redirect(url_for('main.dashboard'))

# Dans app/routes.py

@main.route('/start-trial', methods=['POST'])
@login_required
def start_trial():
    """
    Démarre la période d'essai pour un utilisateur, mais seulement s'il n'en a jamais eu.
    """
    
    # 1. Vérification de Sécurité :
    # On s'assure que l'utilisateur n'est pas déjà un abonné actif
    # ET qu'il n'a jamais eu d'essai par le passé (la colonne trial_ends_at doit être vide).
    if current_user.subscription_status == 'active' or current_user.trial_ends_at is not None:
        flash("Vous avez déjà bénéficié d'une période d'essai et n'êtes plus éligible.", "warning")
        return redirect(url_for('main.dashboard'))

    # 2. Si les vérifications passent, on démarre l'essai
    try:
        # On définit la date de fin de l'essai à 48 heures dans le futur
        current_user.trial_ends_at = datetime.utcnow() + timedelta(hours=48)
        
        # On crée une notification pour l'utilisateur
        notif_content = "Bienvenue ! Votre période d'essai de 48 heures a commencé."
        
        # On importe le modèle Notification ici pour éviter tout risque d'importation circulaire
        from .models import Notification
        db.session.add(Notification(user_id=current_user.id, content=notif_content))
        
        # On sauvegarde les changements dans la base de données
        db.session.commit()
        
        flash("Votre période d'essai de 48h a commencé ! Connectez une page pour en profiter.", "success")
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur lors du démarrage de l'essai pour {current_user.email}: {e}")
        flash("Une erreur est survenue. Veuillez réessayer.", "danger")

    return redirect(url_for('main.dashboard'))

# --- NOUVELLE ROUTE ---
@main.route('/pricing')
@login_required
def pricing():
    return render_template('pricing.html')



@main.route('/payment-success')
@login_required
def payment_success():
    # ... (inchangé)
    return render_template('payment_success.html')


# Dans app/routes.py

@main.route('/create-fedapay-checkout', methods=['POST'])
@login_required
def create_fedapay_checkout():
    """Crée une transaction Fedapay en demandant la tokenisation de la carte."""
    
    # 1. On récupère l'ID du plan envoyé par le formulaire (ex: 'pro_monthly')
    plan_id = request.form.get('plan_id')
    
    # 2. On vérifie que ce plan est bien défini dans notre configuration
    if not plan_id or plan_id not in FEDAPAY_PLANS:
        flash("Forfait de paiement non valide.", "danger")
        return redirect(url_for('main.pricing'))

    # 3. On récupère les détails du plan depuis notre dictionnaire de configuration
    plan_info = FEDAPAY_PLANS[plan_id]
    amount = plan_info['amount']
    plan_name = plan_info['plan_name'] # 'pro' ou 'business'
    
    # On stocke l'ID complet du plan dans la session pour le retrouver après le paiement
    session['pending_plan'] = plan_id

    # Configuration de l'appel à l'API Fedapay
    api_base_url = current_app.config['FEDAPAY_API_BASE']
    api_key = current_app.config['FEDAPAY_SECRET_KEY']
    url = f"{api_base_url}/transactions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # Données envoyées à Fedapay pour créer la transaction
    data = {
        "description": f"Abonnement MinuteFoot - Forfait {plan_name.capitalize()}",
        "amount": amount,
        "currency": {"iso": "XOF"},
        "callback_url": url_for('main.fedapay_callback', _external=True),
        "customer": { "email": current_user.email },
        "tokenize": True  # Clé essentielle pour demander la sauvegarde du moyen de paiement
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status() # Lève une erreur si la requête HTTP échoue
        res_data = response.json()
        payment_url = res_data['v1/transaction']['payment_url']
        return redirect(payment_url)
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la création de la transaction Fedapay: {e}")
        flash("Une erreur est survenue avec le service de paiement. Veuillez réessayer.", "danger")
    
    return redirect(url_for('main.pricing'))



# Dans app/routes.py

@main.route('/manage-fedapay-subscription')
@login_required
def manage_fedapay_subscription():
    """Affiche la page de confirmation pour l'annulation d'un abonnement Fedapay."""
    if current_user.subscription_provider != 'fedapay' or current_user.subscription_status != 'active':
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('main.dashboard'))
    return render_template('cancel_fedapay.html')


@main.route('/cancel-fedapay-subscription', methods=['POST'])
@login_required
def cancel_fedapay_subscription():
    """Traite l'annulation d'un abonnement Fedapay en mettant à jour la BDD."""
    if current_user.subscription_provider != 'fedapay' or current_user.subscription_status != 'active':
        flash("Action non valide.", "danger")
        return redirect(url_for('main.dashboard'))

    try:
        # On désactive l'abonnement dans notre base de données
        current_user.subscription_status = 'inactive'
        current_user.subscription_plan = None
        current_user.subscription_expires_at = None # On nettoie la date d'expiration
        db.session.commit()
        
        # On peut aussi annuler l'abonnement côté Fedapay via leur API si c'est possible
        # pour arrêter les futurs paiements, mais pour l'instant on se contente de désactiver
        # l'accès dans notre application.
        
        flash("Votre abonnement a été annulé avec succès. Vous pouvez maintenant choisir un nouveau forfait.", "success")
        return redirect(url_for('main.pricing')) # On redirige vers la page des tarifs

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur lors de l'annulation Fedapay: {e}")
        flash("Une erreur est survenue lors de l'annulation. Veuillez réessayer.", "danger")
        return redirect(url_for('main.dashboard'))


# Dans app/routes.py

@main.route('/fedapay/callback')
@login_required
def fedapay_callback():
    """
    Gère le retour de Fedapay après un paiement.
    Vérifie le statut, met à jour l'abonnement en utilisant la configuration des plans.
    """
    transaction_id = request.args.get('id')
    if not transaction_id:
        flash("ID de transaction manquant lors du retour du service de paiement.", "danger")
        return redirect(url_for('main.dashboard'))
    
    api_base_url = current_app.config['FEDAPAY_API_BASE']
    api_key = current_app.config['FEDAPAY_SECRET_KEY']
    url = f"{api_base_url}/transactions/{transaction_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        res_data = response.json()
        
        transaction_data = res_data['v1/transaction']
        transaction_status = transaction_data['status']
        
        if transaction_status == 'approved':
            # 1. On récupère l'ID du plan stocké dans la session (ex: 'pro_monthly')
            plan_id = session.pop('pending_plan', 'unknown')
            
            if plan_id not in FEDAPAY_PLANS:
                flash("Erreur lors de la validation de votre forfait. Veuillez contacter le support.", "danger")
                return redirect(url_for('main.dashboard'))

            # 2. On récupère les informations de ce plan depuis notre dictionnaire centralisé
            plan_info = FEDAPAY_PLANS[plan_id]
            plan_name = plan_info['plan_name'] # 'pro' ou 'business'
            duration_days = plan_info['duration_days'] # 30 ou 365

            # 3. Mise à jour complète de l'utilisateur
            current_user.subscription_status = 'active'
            current_user.subscription_plan = plan_name
            current_user.subscription_provider = 'fedapay'
            current_user.trial_ends_at = None
            current_user.next_billing_date = (datetime.utcnow() + timedelta(days=duration_days)).date()

            # Enregistrement de l'ID client Fedapay et du token de paiement
            customer_id = transaction_data.get('customer_id')
            if customer_id:
                current_user.provider_customer_id = str(customer_id)
            try:
                token_id = transaction_data.get('token', {}).get('id')
                if token_id:
                    current_user.fedapay_token = token_id
            except Exception:
                current_app.logger.warning(f"Token Fedapay non trouvé pour la transaction {transaction_id}")
            
            # 4. Création de la notification
            amount_paid = transaction_data.get('amount')
            notif_content = f"Merci ! Votre abonnement au forfait {plan_name.capitalize()} est actif (Montant payé: {amount_paid} XOF)."
            db.session.add(Notification(user_id=current_user.id, content=notif_content))

            # 5. On valide toutes les modifications
            db.session.commit()
            
            return redirect(url_for('main.payment_success'))
        else:
            flash(f"Le paiement n'a pas pu être validé (statut : {transaction_status}).", "danger")
            return redirect(url_for('main.dashboard'))

    except Exception as e:
        current_app.logger.error(f"Erreur dans le callback Fedapay: {e}")
        flash("Une erreur est survenue lors de la vérification de votre paiement.", "danger")
        
    return redirect(url_for('main.dashboard'))


# Dans app/routes.py

@main.route('/profile')
@login_required
def profile():
    """Affiche la page de profil de l'utilisateur."""
    return render_template('profile.html', title='Mon Profil')


# Dans app/routes.py

@main.route('/notifications/mark-as-read', methods=['POST'])
@login_required
def mark_notifications_as_read():
    """Marque toutes les notifications non lues de l'utilisateur comme lues."""
    try:
        Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
        db.session.commit()
        return {'status': 'success'}
    except Exception as e:
        db.session.rollback()
        return {'status': 'error', 'message': str(e)}, 500
    


# Dans app/routes.py

@main.route('/notifications/delete/<int:notification_id>', methods=['POST'])
@login_required
def delete_notification(notification_id):
    """Supprime une notification spécifique."""
    # On cherche la notification dans la base de données
    notif = Notification.query.get_or_404(notification_id)
    
    # Sécurité : on vérifie que l'utilisateur est bien le propriétaire de la notification
    if notif.user_id != current_user.id:
        # Si quelqu'un essaie de supprimer la notif d'un autre, on bloque
        return {'status': 'error', 'message': 'Action non autorisée'}, 403

    try:
        db.session.delete(notif)
        db.session.commit()
        return {'status': 'success'}
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur lors de la suppression de la notification : {e}")
        return {'status': 'error', 'message': 'Erreur interne du serveur'}, 500

@main.route('/notifications/clear-all', methods=['POST'])
@login_required
def clear_all_notifications():
    """Supprime toutes les notifications de l'utilisateur."""
    try:
        # On supprime en masse toutes les notifications de l'utilisateur connecté
        Notification.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        return {'status': 'success'}
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur lors du nettoyage des notifications : {e}")
        return {'status': 'error', 'message': 'Erreur interne du serveur'}, 500


@main.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    """Affiche la page principale de l'administration."""
    return render_template('admin.html')

# Dans app/routes.py

@main.route('/support')
def support():
    """Affiche la page de support et FAQ."""
    return render_template('support.html', title='Support')

@main.route('/admin/notify-all', methods=['POST'])
@login_required
@admin_required
def admin_notify_all():
    """Envoie une notification à tous les utilisateurs."""
    message = request.form.get('message')
    if not message:
        flash("Le message ne peut pas être vide.", "warning")
        return redirect(url_for('main.admin_dashboard'))

    try:
        # On récupère tous les utilisateurs
        all_users = User.query.all()
        
        # On crée une notification pour chaque utilisateur
        for user in all_users:
            new_notification = Notification(user_id=user.id, content=message)
            db.session.add(new_notification)
        
        # On sauvegarde toutes les nouvelles notifications en une seule fois
        db.session.commit()
        flash(f"Notification envoyée avec succès à {len(all_users)} utilisateur(s).", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Une erreur est survenue : {e}", "danger")
        current_app.logger.error(f"Erreur envoi notif admin: {e}")

    return redirect(url_for('main.admin_dashboard'))


# Dans app/routes.py, dans la section des routes admin

@main.route('/admin/publish-news', methods=['POST'])
@login_required
@admin_required
def admin_publish_news():
    """Prend une actualité depuis le formulaire admin et la publie."""
    title = request.form.get('title')
    content = request.form.get('content')

    if not title or not content:
        flash("Le titre et le contenu de l'actualité sont requis.", "warning")
        return redirect(url_for('main.admin_dashboard'))

    try:
        # 1. Récupérer toutes les pages des abonnés Business actifs
        business_pages = db.session.query(FacebookPage).join(User).filter(
            FacebookPage.is_active == True,
            User.subscription_plan == 'business'
        ).all()

        # 2. Construire le message à publier
        message = f"🚨 **ACTU EXCLUSIVE** 🚨\n\n**{title}**\n\n{content}"

        # 3. Utiliser notre fonction de broadcast existante
        # Elle va enregistrer dans l'historique 'Broadcast' et publier sur les pages
        # On a besoin de ça pour broadcast
        tasks.broadcast_to_facebook(business_pages, message)

        # 4. Enregistrer l'actualité dans l'historique des news pour la cohérence
        new_news = PublishedNews(
            title=title,
            content=content,
            source='admin' # On spécifie que ça vient de l'admin
        )
        db.session.add(new_news)
        db.session.commit()

        flash("L'actualité a été publiée avec succès pour les abonnés Business.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Une erreur est survenue lors de la publication : {e}", "danger")
        current_app.logger.error(f"Erreur publication actu admin: {e}")

    return redirect(url_for('main.admin_dashboard'))


# Dans app/routes.py

# ... (vos autres routes)

@main.route('/privacy-policy')
def privacy_policy():
    """Affiche la page de la politique de confidentialité."""
    return render_template('privacy_policy.html', title='Politique de Confidentialité')

@main.route('/terms-of-service')
def terms_of_service():
    """Affiche la page des conditions générales d'utilisation."""
    return render_template('terms_of_service.html', title='Conditions Générales d\'Utilisation')


# Dans la section des routes d'administration de app/routes.py

@main.route('/admin/users')
@login_required
@admin_required
def admin_users():
    """Affiche la liste de tous les utilisateurs pour l'administration."""
    # On récupère tous les utilisateurs sauf le superadmin lui-même pour éviter qu'il se modifie
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=all_users)


@main.route('/admin/users/<int:user_id>/set-role', methods=['POST'])
@login_required
def admin_set_role(user_id):
    """Modifie le rôle d'un utilisateur (réservé au superadmin)."""
    # Sécurité : Seul un superadmin peut changer les rôles
    if not current_user.is_superadmin:
        flash("Seul un Super Administrateur peut modifier les rôles.", "danger")
        return redirect(url_for('main.admin_users'))

    user_to_modify = User.query.get_or_404(user_id)
    new_role = request.form.get('role')

    # Sécurité : On ne peut pas modifier un superadmin, ni se modifier soi-même
    if user_to_modify.is_superadmin:
        flash("Le rôle d'un Super Administrateur ne peut pas être modifié.", "danger")
        return redirect(url_for('main.admin_users'))
    
    # Sécurité : On s'assure que le nouveau rôle est valide
    if new_role not in ['admin', 'user']:
        flash("Rôle non valide.", "danger")
        return redirect(url_for('main.admin_users'))

    try:
        user_to_modify.role = new_role
        db.session.commit()
        flash(f"Le rôle de l'utilisateur {user_to_modify.email} a été mis à jour.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Une erreur est survenue : {e}", "danger")

    return redirect(url_for('main.admin_users'))
