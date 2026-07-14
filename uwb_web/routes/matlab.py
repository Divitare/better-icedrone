"""Token-protected MATLAB API endpoints."""

import hmac
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from uwb_web.models import Measurement
from uwb_web.services import session_service

bp = Blueprint('matlab', __name__, url_prefix='/api/matlab')


def _server_time():
    return datetime.now(timezone.utc).isoformat()


def _configured_token():
    config = current_app.config.get('UWB', {})
    return str(config.get('api', {}).get('matlab_token') or '')


def _request_token():
    auth = request.headers.get('Authorization', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return request.args.get('token', '').strip()


@bp.before_request
def require_matlab_token():
    token = _configured_token()
    if not token:
        return jsonify({
            'error': 'matlab_api_disabled',
            'message': 'Set api.matlab_token in config.yaml or UWB_MATLAB_TOKEN.',
        }), 503

    provided = _request_token()
    if not provided or not hmac.compare_digest(provided, token):
        return jsonify({'error': 'unauthorized'}), 401


def _measurement_to_dict(m):
    return {
        'id': m.id,
        'session_id': m.session_id,
        'session_name': m.session.name if m.session else None,
        'device_id': m.device_id,
        'device_hex': m.device.short_addr_hex if m.device else None,
        'device_label': m.device.label if m.device else None,
        'timestamp_utc': m.pi_received_at_utc.isoformat() if m.pi_received_at_utc else None,
        'range_m': m.range_m,
        'rx_power_dbm': m.rx_power_dbm,
    }


@bp.route('/measurements')
def measurements():
    """Return measurements newer than since_id, ordered oldest to newest."""
    since_id = request.args.get('since_id', 0, type=int)
    limit = request.args.get('limit', 500, type=int)
    device_id = request.args.get('device_id', type=int)
    session_id = request.args.get('session_id', type=int)

    limit = max(1, min(limit, 5000))

    q = Measurement.query
    if since_id:
        q = q.filter(Measurement.id > since_id)
    if device_id:
        q = q.filter_by(device_id=device_id)
    if session_id:
        q = q.filter_by(session_id=session_id)

    rows = q.order_by(Measurement.id.asc()).limit(limit).all()
    latest_id = rows[-1].id if rows else since_id

    return jsonify({
        'server_time_utc': _server_time(),
        'count': len(rows),
        'latest_id': latest_id,
        'measurements': [_measurement_to_dict(m) for m in rows],
    })


@bp.route('/latest')
def latest():
    """Return current in-memory live values for each seen device."""
    from uwb_web import get_serial_worker

    worker = get_serial_worker()
    live = worker.get_live_data() if worker else {}
    position = worker.get_position().get('position') if worker else None

    devices = []
    for addr, info in sorted(live.items()):
        devices.append({
            'device_hex': addr,
            'device_id': info.get('device_id'),
            'device_label': info.get('label'),
            'range_m': info.get('range_m'),
            'rx_power_dbm': info.get('rx_power_dbm'),
            'last_seen_utc': info.get('last_seen'),
            'is_anchor': info.get('is_anchor'),
        })

    return jsonify({
        'server_time_utc': _server_time(),
        'devices': devices,
        'position': position,
    })


@bp.route('/status')
def status():
    """Return serial worker status and active measurement session."""
    from uwb_web import get_serial_worker

    worker = get_serial_worker()
    active = session_service.get_active_session()

    return jsonify({
        'server_time_utc': _server_time(),
        'serial': worker.stats if worker else {},
        'active_session': active.to_dict() if active else None,
    })
