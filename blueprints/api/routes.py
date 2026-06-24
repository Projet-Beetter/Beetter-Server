import re
import jwt
from flask import request, jsonify, current_app
from datetime import datetime, timezone, timedelta
from ...models import db, ApiKey, User, Beehive, Alert
from ..utils.influxdb import write_push_data, query_chart_data
from . import api_bp


# ── JWT helpers ────────────────────────────────────────────────────────────────

def _issue_jwt(user):
    now = datetime.now(timezone.utc)
    payload = {
        'sub': user.username,
        'role': user.role,
        'iat': now,
        'exp': now + timedelta(days=30),
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')


def _decode_jwt(token):
    try:
        return jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
    except jwt.PyJWTError:
        return None


# ── Authentication helper ──────────────────────────────────────────────────────

def _authenticate():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]

    payload = _decode_jwt(token)
    if payload:
        return payload

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
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'status': 'ok'})


@api_bp.route('/auth/verify', methods=['POST'])
def api_verify():
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
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(force=True, silent=True)
    if not payload or 'beehives' not in payload:
        return jsonify({'error': 'Invalid payload'}), 400

    written = 0

    # ── Sensor data ───────────────────────────────────────────────────────────
    for hive in payload.get('beehives', []):
        bid  = hive.get('id')
        name = hive.get('name') or str(bid)
        data = hive.get('data', [])
        if bid is None:
            continue

        # Auto-create beehive in PostgreSQL if needed
        if not Beehive.query.get(str(bid)):
            db.session.add(Beehive(id=str(bid), name=name))
            db.session.commit()

        if data:
            try:
                write_push_data(str(bid), data)
                written += len(data)
            except Exception as e:
                return jsonify({'error': f'InfluxDB write error: {e}'}), 500

    # ── Alerts ────────────────────────────────────────────────────────────────
    alerts_written = 0
    db_hives = {h.id: h.name for h in Beehive.query.all()}

    for a in payload.get('alerts', []):
        bid = str(a.get('beehive_id') or a.get('hive_id', ''))
        if not bid:
            continue

        # Parse created_at
        try:
            created_at = datetime.fromisoformat(
                a['created_at'].replace('Z', '+00:00')
            ).replace(tzinfo=None)
        except (KeyError, ValueError):
            created_at = datetime.utcnow()

        # Avoid duplicates (same beehive, same status, same second)
        existing = Alert.query.filter_by(
            beehive_id=bid,
            new_status=a.get('new_status', ''),
            created_at=created_at,
        ).first()
        if existing:
            continue

        alert = Alert(
            beehive_id=bid,
            old_status=a.get('old_status', ''),
            new_status=a.get('new_status', ''),
            source=a.get('source', 'pi_push'),
            note=a.get('note'),
            created_at=created_at,
        )
        db.session.add(alert)
        alerts_written += 1

    if alerts_written:
        db.session.commit()

    return jsonify({
        'status': 'ok',
        'points_written': written,
        'alerts_written': alerts_written,
    }), 201


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

    db_hives = {h.id: h.name for h in Beehive.query.all()}

    beehives = [
        {'id': bid, 'name': db_hives.get(bid), 'latest': vals}
        for bid, vals in influx_data.items()
    ]

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


# ── Alerts endpoint ───────────────────────────────────────────────────────────

@api_bp.route('/alerts')
def get_alerts():
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401

    hive_id = request.args.get('hive_id')
    period  = request.args.get('period', '24h')

    query = Alert.query
    if hive_id:
        query = query.filter_by(beehive_id=hive_id)

    period_map = {'1h': 1, '24h': 24, '7d': 168, '30d': 720}
    hours = period_map.get(period, 24)
    since = datetime.utcnow() - timedelta(hours=hours)
    query = query.filter(Alert.created_at >= since)

    alerts = query.order_by(Alert.created_at.desc()).limit(200).all()
    db_hives = {h.id: h.name for h in Beehive.query.all()}

    # Last alert per hive = current state; active if new_status is not a resolved status
    RESOLVED_STATUSES = {'calm', 'ok', 'no_data', ''}
    last_per_hive = {}
    for a in sorted(alerts, key=lambda x: x.created_at):
        last_per_hive[a.beehive_id] = a

    active_ids = {
        a.id for a in last_per_hive.values()
        if a.new_status not in RESOLVED_STATUSES
    }

    result = []
    for a in alerts:
        d = a.to_dict(beehive_name=db_hives.get(a.beehive_id))
        d['resolved'] = a.id not in active_ids
        result.append(d)

    return jsonify({'alerts': result})