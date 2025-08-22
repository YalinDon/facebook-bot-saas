# config.py
import os
from dotenv import load_dotenv

load_dotenv()

def get_config():
    """Charge les variables d'environnement et retourne un dictionnaire de configuration."""
    
    if not os.environ.get('STRIPE_SECRET_KEY'):
        raise ValueError("ERREUR: STRIPE_SECRET_KEY n'est pas définie dans le fichier .env")

    config = {
        'SECRET_KEY': os.environ.get('SECRET_KEY') or 'une-cle-secrete-difficile-a-deviner',
        'SQLALCHEMY_DATABASE_URI': os.environ.get('DATABASE_URI'),
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'FACEBOOK_APP_ID': os.environ.get('FACEBOOK_APP_ID'),
        'FACEBOOK_APP_SECRET': os.environ.get('FACEBOOK_APP_SECRET'),
        'ENCRYPTION_KEY': os.environ.get('ENCRYPTION_KEY'),
        'STRIPE_PUBLIC_KEY': os.environ.get('STRIPE_PUBLIC_KEY'),
        'STRIPE_SECRET_KEY': os.environ.get('STRIPE_SECRET_KEY'),
        'STRIPE_WEBHOOK_SECRET': os.environ.get('STRIPE_WEBHOOK_SECRET'),
        
        'MAIL_SERVER': os.environ.get('MAIL_SERVER'),
        'MAIL_PORT': int(os.environ.get('MAIL_PORT') or 587),
        'MAIL_USE_TLS': os.environ.get('MAIL_USE_TLS') is not None,
        'MAIL_USERNAME': os.environ.get('MAIL_USERNAME'),
        'MAIL_PASSWORD': os.environ.get('MAIL_PASSWORD'),
        'MAIL_DEFAULT_SENDER': os.environ.get('MAIL_DEFAULT_SENDER'),
        'FEDAPAY_SECRET_KEY': os.environ.get('FEDAPAY_SECRET_KEY'),
        'FEDAPAY_ENV': os.environ.get('FEDAPAY_ENV'),
        'FEDAPAY_API_BASE': os.environ.get('FEDAPAY_API_BASE'),
        'FEDAPAY_WEBHOOK_SECRET': os.environ.get('FEDAPAY_WEBHOOK_SECRET'),
        'LANGUAGES': ['fr', 'en'], 
        'BABEL_DEFAULT_LOCALE': 'fr', # Langue par défaut si rien n'est détecté        
    }
    
    return config