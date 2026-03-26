"""JSON API endpoints and SSE stream."""

from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone
from uwb_web.services import session_service, device_service, measurement_service, config_service
from uwb_web.models import Event, RawLine
from uwb_web.db import db

bp = Blueprint('api', __name__, url_prefix='/api')


def _try_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ---- Status ----

@bp.route('/status')
def status():
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    active = session_service.get_active_session()
    return jsonify({
        'serial': worker.stats if worker else {},
        'session': active.to_dict() if active else None,
    })


# ---- Devices ----

@bp.route('/devices')
def devices():
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    live = worker.get_live_data() if worker else {}
    result = []
    for d in device_service.get_all_devices():
        info = live.get(d.short_addr_hex, {})
        data = d.to_dict()
        data['last_range'] = info.get('range_m')
        data['last_rx_power'] = info.get('rx_power_dbm')
        data['live_last_seen'] = info.get('last_seen')
        result.append(data)
    return jsonify(result)


# ---- Measurements ----

@bp.route('/measurements')
def measurements():
    limit = request.args.get('limit', 100, type=int)
    device_id = request.args.get('device_id', type=int)
    session_id = request.args.get('session_id', type=int)
    start = _try_iso(request.args.get('start'))
    end = _try_iso(request.args.get('end'))
    rows = measurement_service.get_measurements_filtered(
        start=start, end=end, device_id=device_id,
        session_id=session_id, limit=limit,
    )
    return jsonify([m.to_dict() for m in rows])


@bp.route('/measurements', methods=['DELETE'])
def delete_measurements():
    data = request.get_json(silent=True) or {}
    count = measurement_service.delete_measurements_filtered(
        start=_try_iso(data.get('start')),
        end=_try_iso(data.get('end')),
        device_id=data.get('device_id'),
        session_id=data.get('session_id'),
    )
    evt = Event(
        event_time_utc=datetime.now(timezone.utc),
        event_type='data_deleted',
        event_text=f'API: deleted {count} measurements',
    )
    db.session.add(evt)
    db.session.commit()
    return jsonify({'deleted': count})


# ---- Sessions ----

@bp.route('/sessions')
def sessions():
    return jsonify([
        {**s.to_dict(), 'measurement_count': s.measurements.count()}
        for s in session_service.get_all_sessions()
    ])


@bp.route('/sessions/start', methods=['POST'])
def start_session():
    data = request.get_json(silent=True) or {}
    session = session_service.create_session(name=data.get('name'))
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.start_logging(session.id)
    return jsonify(session.to_dict())


@bp.route('/sessions/end', methods=['POST'])
def end_session():
    active = session_service.get_active_session()
    if active:
        session_service.end_session(active.id)
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.stop_logging()
    return jsonify({'ok': True})


@bp.route('/sessions/<int:sid>', methods=['DELETE'])
def delete_session(sid):
    return jsonify({'ok': session_service.delete_session(sid)})


# ---- Events ----

@bp.route('/events')
def events():
    limit = request.args.get('limit', 50, type=int)
    rows = Event.query.order_by(Event.event_time_utc.desc()).limit(limit).all()
    return jsonify([e.to_dict() for e in rows])


# ---- Config ----

@bp.route('/config', methods=['GET'])
def get_config():
    return jsonify(config_service.get_all_config())


@bp.route('/config', methods=['POST'])
def set_config():
    data = request.get_json(silent=True) or {}
    for key, value in data.items():
        config_service.set_config(key, value)
    return jsonify({'ok': True})


# ---- Destructive ----

@bp.route('/clear-all', methods=['POST'])
def clear_all():
    data = request.get_json(silent=True) or {}
    if data.get('confirm') != 'DELETE ALL DATA':
        return jsonify({'error': 'Confirmation text must be "DELETE ALL DATA"'}), 400
    measurement_service.clear_all_data()
    return jsonify({'ok': True})


# ---- SSE ----

@bp.route('/sse')
def sse_stream():
    from uwb_web import get_sse_broadcaster
    broadcaster = get_sse_broadcaster()
    if not broadcaster:
        return Response('SSE not available', status=503)

    def generate():
        for data in broadcaster.subscribe():
            yield data

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )
