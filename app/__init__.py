# app/__init__.py
from flask_babel import Babel
import os
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user # <-- AJOUT : On importe current_user
from flask_apscheduler import APScheduler
from flask_mail import Mail
from datetime import datetime
from config import get_config
from flask_moment import Moment
# --- Middleware pour la correction TLS/HTTPS derrière un proxy ---
class TlsFixMiddleware:
    def __init__(self, app):
        self.app = app
    def __call__(self, environ, start_response):
        scheme = environ.get('HTTP_X_FORWARDED_PROTO')
        if scheme == 'https' :
            environ['wsgi.url_scheme'] = 'https'
        return self.app(environ, start_response)

# --- Initialisation des extensions ---
db = SQLAlchemy()
login_manager = LoginManager()
scheduler = APScheduler()
mail = Mail()
moment = Moment()
login_manager.login_view = 'main.login'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page.'
login_manager.login_message_category = 'info'
babel = Babel()
# --- Application Factory ---
def create_app():
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_folder = os.path.join(project_root, 'templates')
    static_folder = os.path.join(project_root, 'static')
    
    app = Flask(__name__, 
                template_folder=template_folder, 
                static_folder=static_folder,
                static_url_path='/static')
    
    app.wsgi_app = TlsFixMiddleware(app.wsgi_app)
    
    # On charge la configuration depuis notre fonction.
    app.config.from_mapping(get_config())

    babel.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    scheduler.init_app(app)
    #scheduler.start()
    mail.init_app(app)
    moment.init_app(app)
    # On importe les modèles ici pour éviter les importations circulaires.
    from .models import User, Notification # <-- AJOUT : On importe Notification
    
    # --- DÉBUT DE LA MODIFICATION ---
    # On regroupe toutes les variables globales dans un seul context_processor.
    @app.context_processor
    def inject_global_vars():
        """Injecte des variables dans le contexte de tous les templates."""
        
        # On définit un dictionnaire pour stocker nos variables
        global_vars = {'now': datetime.utcnow}
        
        # Si un utilisateur est connecté, on ajoute ses notifications
        if current_user.is_authenticated:
            # Récupère les 5 dernières notifications pour l'affichage
            notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.timestamp.desc()).limit(5).all()
            # Compte le nombre de notifications non lues pour le badge
            unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
            
            global_vars['notifications'] = notifications
            global_vars['unread_notifications'] = unread_count
        
        return global_vars
    # --- FIN DE LA MODIFICATION ---

    # Flask-Login a besoin de savoir comment charger un utilisateur à partir de son ID.
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Importe et enregistre le Blueprint qui contient nos routes.
    from app.routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app