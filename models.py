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
    """A registered local instance (Raspberry Pi). The `key` field is the Bearer token used for /api/push."""
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    key = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_hex(32))
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    last_used_at = db.Column(db.DateTime)
    last_push_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_push_status = db.Column(db.String(20), default='never')
    last_push_message = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    beehives = db.relationship('Beehive', backref='instance', lazy=True,
                               foreign_keys='Beehive.instance_id')

    @property
    def push_status_color(self):
        from datetime import timezone as _tz
        if not self.last_push_at or self.last_push_status == 'never':
            return 'secondary'
        if self.last_push_status == 'error':
            return 'danger'
        lpa = self.last_push_at
        if lpa.tzinfo is None:
            lpa = lpa.replace(tzinfo=_tz.utc)
        age = (datetime.now(_tz.utc) - lpa).total_seconds()
        if age < 1800:    # < 30 min
            return 'success'
        if age < 86400:   # < 24 h
            return 'warning'
        return 'danger'


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
    id          = db.Column(db.String(20), primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    instance_id = db.Column(db.Integer, db.ForeignKey('api_keys.id', ondelete='SET NULL'), nullable=True)

    def to_dict(self):
        return {'id': self.id, 'name': self.name}

