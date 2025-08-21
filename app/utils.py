<<<<<<< HEAD
# app/utils.py

from flask import url_for, render_template
from flask_mail import Message
from app import mail
import hmac
import hashlib
from flask import request, current_app
from . import mail, db
from .models import Broadcast

def send_reset_email(user):
    """Génère le jeton, crée l'email et l'envoie."""
    token = user.get_reset_token()
    msg = Message('Réinitialisation de votre mot de passe',
                  sender="minutefoot1@gmail.com",  # Remplacez par votre email
                  recipients=[user.email])
    
    # Le corps de l'email sera généré à partir d'un template HTML
    msg.html = render_template('email/reset_password.html',
                               user=user,
                               token=token)
    try:
        mail.send(msg)
        return True
    except Exception as e:
        # En cas d'erreur, on peut la logger pour le débogage
        print(f"Erreur lors de l'envoi de l'email : {e}")
        return False
    
    
# Dans app/utils.py

def is_valid_fedapay_signature():
    """Vérifie si la signature de la requête webhook de Fedapay est valide."""
    # Le nom de l'en-tête peut varier, consultez la documentation de Fedapay
    # Exemples courants : 'Feda-Signature', 'X-Fedapay-Signature'
    fedapay_signature = request.headers.get('Feda-Signature')
    
    webhook_secret = current_app.config.get('FEDAPAY_WEBHOOK_SECRET')

    if not fedapay_signature or not webhook_secret:
        return False

    # On a besoin du corps brut de la requête
    payload = request.get_data()
    
    try:
        # On calcule notre propre signature HMAC-SHA1 (Fedapay utilise SHA1)
        computed_hash = hmac.new(webhook_secret.encode('utf-8'), payload, hashlib.sha1)
        computed_signature = computed_hash.hexdigest()

        # On compare notre signature avec celle envoyée par Fedapay
        return hmac.compare_digest(computed_signature, fedapay_signature)
    except Exception as e:
        current_app.logger.error(f"Erreur de vérification de signature Fedapay: {e}")
        return False

=======
# app/utils.py

from flask import url_for, render_template
from flask_mail import Message
from app import mail
import hmac
import hashlib
from flask import request, current_app
from . import mail, db
from .models import Broadcast

def send_reset_email(user):
    """Génère le jeton, crée l'email et l'envoie."""
    token = user.get_reset_token()
    msg = Message('Réinitialisation de votre mot de passe',
                  sender="jeanyalinmon@gmail.com",  # Remplacez par votre email
                  recipients=[user.email])
    
    # Le corps de l'email sera généré à partir d'un template HTML
    msg.html = render_template('email/reset_password.html',
                               user=user,
                               token=token)
    try:
        mail.send(msg)
        return True
    except Exception as e:
        # En cas d'erreur, on peut la logger pour le débogage
        print(f"Erreur lors de l'envoi de l'email : {e}")
        return False
    
    
# Dans app/utils.py

def is_valid_fedapay_signature():
    """Vérifie si la signature de la requête webhook de Fedapay est valide."""
    # Le nom de l'en-tête peut varier, consultez la documentation de Fedapay
    # Exemples courants : 'Feda-Signature', 'X-Fedapay-Signature'
    fedapay_signature = request.headers.get('Feda-Signature')
    
    webhook_secret = current_app.config.get('FEDAPAY_WEBHOOK_SECRET')

    if not fedapay_signature or not webhook_secret:
        return False

    # On a besoin du corps brut de la requête
    payload = request.get_data()
    
    try:
        # On calcule notre propre signature HMAC-SHA1 (Fedapay utilise SHA1)
        computed_hash = hmac.new(webhook_secret.encode('utf-8'), payload, hashlib.sha1)
        computed_signature = computed_hash.hexdigest()

        # On compare notre signature avec celle envoyée par Fedapay
        return hmac.compare_digest(computed_signature, fedapay_signature)
    except Exception as e:
        current_app.logger.error(f"Erreur de vérification de signature Fedapay: {e}")
        return False

>>>>>>> fbb69e9e5633005d19d8e9365d836fbf1f87dd2a
