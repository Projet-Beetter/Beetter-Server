from flask import request, jsonify
from datetime import datetime, timezone
from ...models import db, ApiKey, UserSession, User
from ..utils.influxdb import write_push_data, query_chart_data
from . import api_bp


# ── Authentication helper ──────────────────────────────────────────────────────

def _authenticate():
    """Return an ApiKey or UserSession if the Bearer token is valid, else None."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]

    # API key (used by Raspberry Pi and direct integrations)
    key = ApiKey.query.filter_by(key=token, enabled=True).first()
    if key:
        key.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
        return key

    # Mobile session token
    session = UserSession.query.filter_by(token=token).first()
    if session and session.is_valid:
        return session

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

    session = UserSession(user_id=user.id)
    db.session.add(session)
    db.session.commit()

    return jsonify({
        'token': session.token,
        'username': user.username,
        'expires_at': session.expires_at.isoformat(),
    })


@api_bp.route('/auth/logout', methods=['POST'])
def api_logout():
    credential = _authenticate()
    if credential is None:
        return jsonify({'error': 'Unauthorized'}), 401
    if isinstance(credential, UserSession):
        db.session.delete(credential)
        db.session.commit()
    return jsonify({'status': 'ok'})


# ── Push endpoint (called by Raspberry Pi) ────────────────────────────────────

@api_bp.route('/push', methods=['POST'])
def push():
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(force=True, silent=True)
    if not payload or 'beehives' not in payload:
        return jsonify({'error': 'Invalid payload'}), 400

    written = 0
    for hive in payload.get('beehives', []):
        bid = hive.get('id')
        data = hive.get('data', [])
        if bid is not None and data:
            try:
                write_push_data(str(bid), data)
                written += len(data)
            except Exception as e:
                return jsonify({'error': f'InfluxDB write error: {e}'}), 500

    return jsonify({'status': 'ok', 'points_written': written}), 201


# ── Android app data endpoints ─────────────────────────────────────────────────

@api_bp.route('/beehives')
def list_beehives():
    if not _authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
    from ..utils.influxdb import list_beehives as _list
    try:
        data = _list()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'beehives': [
        {'id': bid, 'latest': vals} for bid, vals in data.items()
    ]})


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
