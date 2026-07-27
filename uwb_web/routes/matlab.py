"""Token-protected MATLAB API endpoints."""

import hmac
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from uwb_web.db import db
from uwb_web.models import Measurement, Device, FusedPose
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


def _measurement_query(device_id=None, session_id=None):
    q = Measurement.query
    if device_id:
        q = q.filter_by(device_id=device_id)
    if session_id:
        q = q.filter_by(session_id=session_id)
    return q


def _latest_measurement_id(device_id=None, session_id=None):
    latest = (
        _measurement_query(device_id=device_id, session_id=session_id)
        .with_entities(func.max(Measurement.id))
        .scalar()
    )
    return int(latest or 0)


@bp.route('/latest-id')
def latest_id():
    """Return only the newest measurement id for cursor initialisation."""
    device_id = request.args.get('device_id', type=int)
    session_id = request.args.get('session_id', type=int)
    latest = _latest_measurement_id(device_id=device_id, session_id=session_id)
    return jsonify({
        'server_time_utc': _server_time(),
        'latest_id': latest,
    })


@bp.route('/measurements')
def measurements():
    """Return measurements newer than since_id, ordered oldest to newest.

    If since_id is omitted, initialise the live cursor at the current newest
    id without returning historical rows. This lets MATLAB start "from now".
    """
    since_id_arg = request.args.get('since_id')
    since_id = request.args.get('since_id', 0, type=int)
    limit = request.args.get('limit', 500, type=int)
    device_id = request.args.get('device_id', type=int)
    session_id = request.args.get('session_id', type=int)

    limit = max(1, min(limit, 5000))
    database_latest_id = _latest_measurement_id(device_id=device_id, session_id=session_id)

    if since_id_arg is None:
        return jsonify({
            'server_time_utc': _server_time(),
            'count': 0,
            'latest_id': database_latest_id,
            'database_latest_id': database_latest_id,
            'measurements': [],
        })

    q = _measurement_query(device_id=device_id, session_id=session_id)
    if since_id:
        q = q.filter(Measurement.id > since_id)

    rows = q.order_by(Measurement.id.asc()).limit(limit).all()
    latest_id = rows[-1].id if rows else since_id

    return jsonify({
        'server_time_utc': _server_time(),
        'count': len(rows),
        'latest_id': latest_id,
        'database_latest_id': database_latest_id,
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


def _parse_dt(value):
    """Parse an ISO-8601 timestamp, tolerating a trailing 'Z'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


@bp.route('/anchors')
def anchors():
    """Anchor devices with known coordinates, for MATLAB frame setup.

    MATLAB uses these if present; if the list is empty (or the Pi is
    unreachable) MATLAB falls back to its internal anchor table.
    """
    rows = (
        Device.query
        .filter_by(is_anchor=True)
        .filter(Device.x.isnot(None), Device.y.isnot(None), Device.z.isnot(None))
        .order_by(Device.short_addr_hex)
        .all()
    )
    anchor_list = [{
        'device_id': d.id,
        'short_addr_hex': d.short_addr_hex,
        'label': d.label,
        'x': d.x, 'y': d.y, 'z': d.z,
    } for d in rows]
    return jsonify({
        'server_time_utc': _server_time(),
        'count': len(anchor_list),
        'anchors': anchor_list,
    })


@bp.route('/position', methods=['GET', 'POST'])
def position():
    """GET: latest fused pose + history for the website.
    POST: receive a fused pose from the external MATLAB filter.
    """
    from uwb_web import get_serial_worker, get_sse_broadcaster

    worker = get_serial_worker()

    if request.method == 'GET':
        pose = worker.get_fused_pose() if worker else {'pose': None, 'history': []}
        return jsonify({'server_time_utc': _server_time(), **pose})

    # ---- POST: store a fused pose ----
    data = request.get_json(silent=True) or {}

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _vec(name, n):
        v = data.get(name)
        if isinstance(v, (list, tuple)) and len(v) >= n:
            return [_num(v[i]) for i in range(n)]
        return [None] * n

    pos = data.get('position')
    if not isinstance(pos, (list, tuple)) or len(pos) < 3:
        return jsonify({'error': 'bad_request',
                        'message': 'position must be [x, y, z]'}), 400
    x, y, z = _num(pos[0]), _num(pos[1]), _num(pos[2])
    if None in (x, y, z):
        return jsonify({'error': 'bad_request',
                        'message': 'position must be numeric'}), 400

    quat = _vec('orientation_quat', 4)
    eul = _vec('euler_deg', 3)
    vel = _vec('velocity', 3)
    std = _vec('pos_std', 3)

    num_anchors = data.get('num_anchors')
    try:
        num_anchors = int(num_anchors) if num_anchors is not None else None
    except (TypeError, ValueError):
        num_anchors = None

    now_utc = datetime.now(timezone.utc)
    matlab_time = _parse_dt(data.get('matlab_time_utc'))

    entry = {
        'x': x, 'y': y, 'z': z,
        'quat': quat,
        'euler_deg': eul,
        'velocity': vel,
        'pos_std': std,
        'num_anchors': num_anchors,
        'pi_received_at_utc': now_utc.isoformat(),
        'matlab_time_utc': matlab_time.isoformat() if matlab_time else None,
    }

    # 1) live store for the website
    if worker:
        worker.set_fused_pose(entry)

    # 2) persist for CSV export, tied to the worker's current session
    session_id = worker.current_session_id if worker else None
    try:
        db.session.add(FusedPose(
            session_id=session_id,
            pi_received_at_utc=now_utc,
            matlab_time_utc=matlab_time,
            x=x, y=y, z=z,
            qw=quat[0], qx=quat[1], qy=quat[2], qz=quat[3],
            yaw=eul[0], pitch=eul[1], roll=eul[2],
            vx=vel[0], vy=vel[1], vz=vel[2],
            std_x=std[0], std_y=std[1], std_z=std[2],
            num_anchors=num_anchors,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to store fused pose')

    # 3) live push to browsers
    broadcaster = get_sse_broadcaster()
    if broadcaster:
        broadcaster.publish({'type': 'fused_position', **entry})

    return jsonify({'ok': True, 'stored_session_id': session_id})
