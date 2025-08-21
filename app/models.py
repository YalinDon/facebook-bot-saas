<<<<<<< HEAD
# app/models.py

# =============================================================================
# === MODÈLE UTILISATEUR ======================================================
# =============================================================================
# app/models.py
# (Assurez-vous que tous les imports nécessaires sont en haut de votre fichier)
from . import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer

# ... (les autres classes de modèles comme FacebookPage, etc.)


class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='user')
    # Statut de l'abonnement, mis à jour par le webhook Stripe
    subscription_status = db.Column(db.String(20), nullable=False, default='inactive')
    
    # Stocke l'ID client de Stripe pour gérer l'abonnement
    stripe_customer_id = db.Column(db.String(120), unique=True, nullable=True)
    
    # Date de création du compte
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Date de fin de la période d'essai
    trial_ends_at = db.Column(db.DateTime, nullable=True)
    
    # --- DÉBUT DE L'AJOUT ---
    # Nouvelle colonne pour stocker le type de forfait (ex: 'pro', 'business')
    subscription_plan = db.Column(db.String(50), nullable=True)
    # Relation avec les pages Facebook de l'utilisateur
    subscription_provider = db.Column(db.String(50), nullable=True)
    provider_customer_id = db.Column(db.String(255), nullable=True)
    subscription_expires_at = db.Column(db.DateTime, nullable=True)
    pages = db.relationship('FacebookPage', backref='owner', lazy=True, cascade="all, delete-orphan")

    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    def __repr__(self):
        return f'<User {self.email}>'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- Les méthodes pour la fonctionnalité "mot de passe oublié" restent INCHANGÉES ---
    
    def get_reset_token(self):
        """Génère un jeton sécurisé pour la réinitialisation du mot de passe."""
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        """Vérifie un jeton et retourne l'utilisateur si le jeton est valide et non expiré."""
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            # Tente de charger le jeton en vérifiant sa date d'expiration (1800s = 30 minutes)
            user_id = s.loads(token, max_age=expires_sec)['user_id']
        except Exception:
            # Si le chargement échoue (jeton invalide, expiré, etc.), retourne None
            return None
        # Si le jeton est valide, retourne l'objet User correspondant
        return User.query.get(user_id)
        
    # --- FIN DES AJOUTS ---

# =============================================================================
# === MODÈLE PAGE FACEBOOK ====================================================
# =============================================================================
class FacebookPage(db.Model):
    __tablename__ = 'facebook_page'

    id = db.Column(db.Integer, primary_key=True)
    
    # Lien vers l'utilisateur propriétaire
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Informations de la page Facebook
    facebook_page_id = db.Column(db.String(100), nullable=False, unique=True)
    page_name = db.Column(db.String(200), nullable=False)
    
    # Le token d'accès chiffré, nécessaire pour publier
    encrypted_page_access_token = db.Column(db.Text, nullable=False)
    
    # Booléen pour que l'utilisateur puisse activer/désactiver le bot pour cette page
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f'<Page {self.page_name} ({self.facebook_page_id})>'
    
    
class Broadcast(db.Model):
    __tablename__ = 'broadcast'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<Broadcast {self.id} - {self.content[:30]}>'
        
        
# Dans app/models.py

# ... (classes User, FacebookPage, etc.)

class Notification(db.Model):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relation pour accéder facilement à l'utilisateur depuis une notification
    user = db.relationship('User', backref=db.backref('notifications', lazy=True, cascade="all, delete-orphan"))

    def __repr__(self):
        return f'<Notification pour l\'utilisateur {self.user_id}>'   
    
# Dans app/models.py

class PublishedNews(db.Model):
    __tablename__ = 'published_news'
    
    id = db.Column(db.Integer, primary_key=True)
    # L'URL peut être vide pour les actus manuelles
    article_url = db.Column(db.String(512), unique=True, nullable=True) 
    title = db.Column(db.String(512), nullable=False)
    content = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # --- NOUVELLE COLONNE ---
    # Pour distinguer les actus du scraper de celles de l'admin
    source = db.Column(db.String(50), nullable=False, default='scraper') # 'scraper' ou 'admin'
    # --- FIN DE L'AJOUT ---

    def __repr__(self):
        return f'<PublishedNews {self.title[:50]}>'   
=======
# app/models.py

# =============================================================================
# === MODÈLE UTILISATEUR ======================================================
# =============================================================================
# app/models.py
# (Assurez-vous que tous les imports nécessaires sont en haut de votre fichier)
from . import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer

# ... (les autres classes de modèles comme FacebookPage, etc.)


class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='user')
    # Statut de l'abonnement, mis à jour par le webhook Stripe
    subscription_status = db.Column(db.String(20), nullable=False, default='inactive')
    
    # Stocke l'ID client de Stripe pour gérer l'abonnement
    stripe_customer_id = db.Column(db.String(120), unique=True, nullable=True)
    
    # Date de création du compte
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Date de fin de la période d'essai
    trial_ends_at = db.Column(db.DateTime, nullable=True)
    
    # --- DÉBUT DE L'AJOUT ---
    # Nouvelle colonne pour stocker le type de forfait (ex: 'pro', 'business')
    subscription_plan = db.Column(db.String(50), nullable=True)
    # Relation avec les pages Facebook de l'utilisateur
    subscription_provider = db.Column(db.String(50), nullable=True)
    provider_customer_id = db.Column(db.String(255), nullable=True)
    subscription_expires_at = db.Column(db.DateTime, nullable=True)
    pages = db.relationship('FacebookPage', backref='owner', lazy=True, cascade="all, delete-orphan")

    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    def __repr__(self):
        return f'<User {self.email}>'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- Les méthodes pour la fonctionnalité "mot de passe oublié" restent INCHANGÉES ---
    
    def get_reset_token(self):
        """Génère un jeton sécurisé pour la réinitialisation du mot de passe."""
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        """Vérifie un jeton et retourne l'utilisateur si le jeton est valide et non expiré."""
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            # Tente de charger le jeton en vérifiant sa date d'expiration (1800s = 30 minutes)
            user_id = s.loads(token, max_age=expires_sec)['user_id']
        except Exception:
            # Si le chargement échoue (jeton invalide, expiré, etc.), retourne None
            return None
        # Si le jeton est valide, retourne l'objet User correspondant
        return User.query.get(user_id)
        
    # --- FIN DES AJOUTS ---

# =============================================================================
# === MODÈLE PAGE FACEBOOK ====================================================
# =============================================================================
class FacebookPage(db.Model):
    __tablename__ = 'facebook_page'

    id = db.Column(db.Integer, primary_key=True)
    
    # Lien vers l'utilisateur propriétaire
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Informations de la page Facebook
    facebook_page_id = db.Column(db.String(100), nullable=False, unique=True)
    page_name = db.Column(db.String(200), nullable=False)
    
    # Le token d'accès chiffré, nécessaire pour publier
    encrypted_page_access_token = db.Column(db.Text, nullable=False)
    
    # Booléen pour que l'utilisateur puisse activer/désactiver le bot pour cette page
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f'<Page {self.page_name} ({self.facebook_page_id})>'
    
    
class Broadcast(db.Model):
    __tablename__ = 'broadcast'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<Broadcast {self.id} - {self.content[:30]}>'
        
        
# Dans app/models.py

# ... (classes User, FacebookPage, etc.)

class Notification(db.Model):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relation pour accéder facilement à l'utilisateur depuis une notification
    user = db.relationship('User', backref=db.backref('notifications', lazy=True, cascade="all, delete-orphan"))

    def __repr__(self):
        return f'<Notification pour l\'utilisateur {self.user_id}>'   
    
# Dans app/models.py

class PublishedNews(db.Model):
    __tablename__ = 'published_news'
    
    id = db.Column(db.Integer, primary_key=True)
    # L'URL peut être vide pour les actus manuelles
    article_url = db.Column(db.String(512), unique=True, nullable=True) 
    title = db.Column(db.String(512), nullable=False)
    content = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # --- NOUVELLE COLONNE ---
    # Pour distinguer les actus du scraper de celles de l'admin
    source = db.Column(db.String(50), nullable=False, default='scraper') # 'scraper' ou 'admin'
    # --- FIN DE L'AJOUT ---

    def __repr__(self):
        return f'<PublishedNews {self.title[:50]}>'   
>>>>>>> fbb69e9e5633005d19d8e9365d836fbf1f87dd2a
    