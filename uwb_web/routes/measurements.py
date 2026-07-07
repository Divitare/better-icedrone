"""Live measurements page."""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from uwb_web.services import measurement_service, session_service, device_service

bp = Blueprint('measurements', __name__)


@bp.route('/measurements')
def index():
    device_id = request.args.get('device_id', type=int)
    session_id = request.args.get('session_id', type=int)
    limit = request.args.get('limit', 200, type=int)

    measurements = measurement_service.get_recent_measurements(
        limit=limit, device_id=device_id, session_id=session_id,
    )
    sessions = session_service.get_all_sessions()
    devices = device_service.get_all_devices()
    active_session = session_service.get_active_session()

    return render_template(
        'measurements.html',
        measurements=measurements,
        sessions=sessions,
        devices=devices,
        active_session=active_session,
        selected_device=device_id,
        selected_session=session_id,
        selected_limit=limit,
    )


@bp.route('/measurements/start', methods=['POST'])
def start():
    name = request.form.get('name', '').strip() or None
    session = session_service.create_session(name=name)

    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.start_logging(session.id)

    flash(f'Measurement "{session.name}" started.', 'success')
    return redirect(url_for('measurements.index', session_id=session.id))


@bp.route('/measurements/end', methods=['POST'])
def end():
    active = session_service.get_active_session()
    if active:
        session_service.end_session(active.id)
        from uwb_web import get_serial_worker
        worker = get_serial_worker()
        if worker:
            worker.stop_logging()
        flash(f'Measurement "{active.name}" stopped.', 'success')
    else:
        flash('No active measurement to stop.', 'info')
    return redirect(url_for('measurements.index'))
