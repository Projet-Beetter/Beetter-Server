from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import UserMixin
from datetime import datetime, timedelta
import secrets

db = SQLAlchemy()
bcrypt = Bcrypt()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='viewer')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    api_keys = db.relationship('ApiKey', backref='owner', lazy=True, cascade='all, delete-orphan')
    sessions = db.relationship('UserSession', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'


class ApiKey(db.Model):
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    key = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_hex(32))
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    last_used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


class UserSession(db.Model):
    """Mobile app session tokens (username+password login)."""
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_hex(32))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=30))

    @property
    def is_valid(self):
        return datetime.utcnow() < self.expires_at


class Beehive(db.Model):
    __tablename__ = 'beehives'
    id         = db.Column(db.String(20), primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'name': self.name}


class Alert(db.Model):
    __tablename__ = 'alerts'
    id          = db.Column(db.Integer, primary_key=True)
    beehive_id  = db.Column(db.String(20), db.ForeignKey('beehives.id'), nullable=False)
    old_status  = db.Column(db.String(20), nullable=False, default='')
    new_status  = db.Column(db.String(20), nullable=False)
    source      = db.Column(db.String(50), nullable=False, default='pi_push')
    note        = db.Column(db.Text, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    beehive     = db.relationship('Beehive', backref=db.backref('alerts', cascade='all, delete-orphan'))

    def to_dict(self, beehive_name=None):
        return {
            'id': self.id,
            'beehive_id': self.beehive_id,
            'beehive_name': beehive_name or self.beehive_id,
            'old_status': self.old_status,
            'new_status': self.new_status,
            'source': self.source,
            'note': self.note,
            'created_at': self.created_at.isoformat() + 'Z',
        }

