# app/models.py (Version Finale pour Production)

from . import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer

class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='user')
    subscription_status = db.Column(db.String(20), nullable=False, default='inactive')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    trial_ends_at = db.Column(db.DateTime, nullable=True)
    subscription_plan = db.Column(db.String(50), nullable=True)
    subscription_provider = db.Column(db.String(50), nullable=True)
    fedapay_token = db.Column(db.String(255), nullable=True)
    next_billing_date = db.Column(db.Date, nullable=True)
    pages = db.relationship('FacebookPage', backref='owner', lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade="all, delete-orphan")

    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    def __repr__(self):
        return f'<User {self.email}>'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_reset_token(self):
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, max_age=expires_sec)['user_id']
        except Exception:
            return None
        return User.query.get(user_id)

class FacebookPage(db.Model):
    __tablename__ = 'facebook_page'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    facebook_page_id = db.Column(db.String(100), nullable=False, unique=True)
    page_name = db.Column(db.String(200), nullable=False)
    encrypted_page_access_token = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f'<Page {self.page_name}>'
    
class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<Notification pour {self.user_id}>'

class Broadcast(db.Model):
    __tablename__ = 'broadcast'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<Broadcast {self.id}>'
        
class PublishedNews(db.Model):
    __tablename__ = 'published_news'
    id = db.Column(db.Integer, primary_key=True)
    article_url = db.Column(db.String(512), unique=True, nullable=True) 
    title = db.Column(db.String(512), nullable=False)
    content = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    source = db.Column(db.String(50), nullable=False, default='scraper')

    def __repr__(self):
        return f'<PublishedNews {self.title[:50]}>'

# --- NOUVELLES TABLES POUR LA MÉMOIRE DU BOT ---

class GlobalState(db.Model):
    """Table de type clé-valeur pour stocker l'état global, comme le hash du résumé."""
    __tablename__ = 'global_state'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

class GlobalMatchState(db.Model):
    """Remplace scores.json. Stocke l'état des matchs en direct."""
    __tablename__ = 'global_match_state'
    id = db.Column(db.Integer, primary_key=True)
    match_key = db.Column(db.String(255), unique=True, nullable=False)
    score = db.Column(db.String(20))
    statut = db.Column(db.String(50))
    minute = db.Column(db.String(50))
    url = db.Column(db.String(512))
    eq1 = db.Column(db.String(100))
    eq2 = db.Column(db.String(100))

class GlobalPublishedMatch(db.Model):
    """Remplace published_finished.json. Stocke les ID des matchs terminés déjà publiés."""
    __tablename__ = 'global_published_match'
    id = db.Column(db.Integer, primary_key=True)
    match_identifier = db.Column(db.String(255), unique=True, nullable=False)
    published_at = db.Column(db.DateTime, default=datetime.utcnow)