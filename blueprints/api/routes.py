import re
import jwt
from flask import request, jsonify, current_app
from datetime import datetime, timezone, timedelta
from ...models import db, ApiKey, User, Beehive, Alert
from ..utils.influxdb import write_push_data, query_chart_data
from . import api_bp


# ── JWT helpers ────────────────────────────────────────────────────────────────

def _issue_jwt(user):
    """Return a signed JWT for a User. Expires in 30 days."""
    now = datetime.now(timezone.utc)
    payload = {
        'sub': user.username,
        'role': user.role,
        'iat': now,
        'exp': now + timedelta(days=30),
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')


def _decode_jwt(token):
    """Return the JWT payload dict or None if invalid/expired."""
    try:
        return jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
    except jwt.PyJWTError:
        return None


# ── Authentication helper ──────────────────────────────────────────────────────

def _authenticate():
    """Return the authenticated identity (ApiKey or JWT payload dict) or None."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]

    # Try JWT first (mobile app sessions)
    payload = _decode_jwt(token)
    if payload:
        return payload

    # Fall back to API key (Raspberry Pi push)
    key = ApiKey.query.filter_by(key=token, enabled=True).first()
    if key:
        key.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
        return key

    return None


# ── Mobile auth endpoints ──────────────────────────────────────────────────────

@api_bp.route('/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    user = User.query.filter_by(username=data.get('username', '')).first()
    if not user or not user.check_password(data.get('password', '')):
        return jsonify({'error': 'Invalid credentials'}), 401

    token = _issue_jwt(user)
    now = datetime.now(timezone.utc)
    return jsonify({
        'token': token,
        'username': user.username,
        'role': user.role,
        'expires_at': (now + timedelta(days=30)).isoformat(),
    })


@api_bp.route('/auth/logout', methods=['POST'])
def api_logout():
    # JWTs are stateless — client simply discards the token.
    # We still require a valid token so random calls don't get 200.
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'status': 'ok'})


@api_bp.route('/auth/verify', methods=['POST'])
def api_verify():
    """Called by a linked app/ instance to validate credentials and receive a JWT.

    Request:  {username, password}
    Response: {valid: true, token: <JWT>, username, role, expires_at}
    """
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    user = User.query.filter_by(username=data.get('username', '')).first()
    if not user or not user.check_password(data.get('password', '')):
        return jsonify({'valid': False, 'error': 'Invalid credentials'}), 401

    token = _issue_jwt(user)
    now = datetime.now(timezone.utc)
    return jsonify({
        'valid': True,
        'token': token,
        'username': user.username,
        'role': user.role,
        'expires_at': (now + timedelta(days=30)).isoformat(),
    })


# ── Push endpoint (called by Raspberry Pi) ────────────────────────────────────

@api_bp.route('/push', methods=['POST'])
def push():
    identity = _authenticate()
    if not identity:
        return jsonify({'error': 'Unauthorized'}), 401

    # Distinguish API key (local instance) from JWT (mobile / human user)
    api_key = identity if isinstance(identity, ApiKey) else None

    payload = request.get_json(force=True, silent=True)
    if not payload or 'beehives' not in payload:
        return jsonify({'error': 'Invalid payload'}), 400

    written = 0
    for hive in payload.get('beehives', []):
        bid  = hive.get('id')
        name = hive.get('name') or str(bid)
        data = hive.get('data', [])
        if bid is None:
            continue

        # Auto-create the beehive in PostgreSQL if not seen before, and link it to the instance
        if not Beehive.query.get(str(bid)):
            new_hive = Beehive(id=str(bid), name=name)
            if api_key:
                new_hive.instance_id = api_key.id
            db.session.add(new_hive)
            db.session.commit()

        if data:
            try:
                write_push_data(str(bid), data)
                written += len(data)
            except Exception as e:
                if api_key:
                    api_key.last_push_status = 'error'
                    api_key.last_push_message = str(e)[:500]
                    db.session.commit()
                return jsonify({'error': f'InfluxDB write error: {e}'}), 500

    if api_key:
        api_key.last_push_at = datetime.now(timezone.utc)
        api_key.last_push_status = 'success'
        api_key.last_push_message = f'{written} points written'
        db.session.commit()

    return jsonify({'status': 'ok', 'points_written': written}), 201

# ── Mobile app data endpoints ──────────────────────────────────────────────────

@api_bp.route('/beehives')
def list_beehives():
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
    from ..utils.influxdb import list_beehives as _list
    try:
        influx_data = _list()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Merge names from PostgreSQL
    db_hives = {h.id: h.name for h in Beehive.query.all()}

    # Build list from InfluxDB data + inject names
    beehives = [
        {'id': bid, 'name': db_hives.get(bid), 'latest': vals}
        for bid, vals in influx_data.items()
    ]

    # Also include DB-registered hives with no InfluxDB data yet
    influx_ids = {b['id'] for b in beehives}
    for hive_id, name in db_hives.items():
        if hive_id not in influx_ids:
            beehives.append({'id': hive_id, 'name': name, 'latest': None})

    return jsonify({'beehives': beehives})


@api_bp.route('/beehives', methods=['POST'])
def create_beehive():
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(force=True, silent=True) or {}
    hive_id = str(data.get('id', '')).strip().upper()
    name    = str(data.get('name', '')).strip()

    if not hive_id or not name:
        return jsonify({'error': 'id and name are required'}), 400

    if not re.match(r'^[A-Z0-9]{1,10}$', hive_id):
        return jsonify({'error': 'id must be alphanumeric, max 10 chars'}), 422

    if Beehive.query.get(hive_id):
        return jsonify({'error': f'Beehive {hive_id} already exists'}), 409

    hive = Beehive(id=hive_id, name=name)
    db.session.add(hive)
    db.session.commit()
    return jsonify(hive.to_dict()), 201


@api_bp.route('/beehives/<beehive_id>/data')
def beehive_data(beehive_id):
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
    range_str = request.args.get('range', '24h')
    try:
        data = query_chart_data(beehive_id, range_str)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(data)


@api_bp.route('/alerts')
def get_alerts():
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401

    hive_id = request.args.get('hive_id')
    period  = request.args.get('period', '24h')

    # 1. All alerts to determine the CURRENT state of each hive
    all_q = Alert.query
    if hive_id:
        all_q = all_q.filter_by(beehive_id=hive_id)
    all_alerts = all_q.order_by(Alert.created_at.asc()).all()

    RESOLVED_STATUSES = {'calm', 'ok', 'no_data', ''}
    last_per_hive = {}
    for a in all_alerts:
        last_per_hive[a.beehive_id] = a

    # Hives still in an alert state
    active_hive_ids = {
        bid for bid, a in last_per_hive.items()
        if a.new_status not in RESOLVED_STATUSES
    }

    # 2. Alerts to display (period window)
    period_map = {'1h': 1, '24h': 24, '7d': 168, '30d': 720}
    hours = period_map.get(period, 24)
    since = datetime.utcnow() - timedelta(hours=hours)

    display_q = Alert.query
    if hive_id:
        display_q = display_q.filter_by(beehive_id=hive_id)
    display_alerts = display_q.filter(
        Alert.created_at >= since
    ).order_by(Alert.created_at.desc()).limit(200).all()

    db_hives = {h.id: h.name for h in Beehive.query.all()}

    result = []
    for a in display_alerts:
        d = a.to_dict(beehive_name=db_hives.get(a.beehive_id))
        is_latest = (last_per_hive.get(a.beehive_id) and
                     last_per_hive[a.beehive_id].id == a.id)
        d['resolved'] = not (is_latest and a.beehive_id in active_hive_ids)
        result.append(d)

    return jsonify({'alerts': result})