"""Live measurements page."""

from flask import Blueprint, render_template, request
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

    return render_template(
        'measurements.html',
        measurements=measurements,
        sessions=sessions,
        devices=devices,
        selected_device=device_id,
        selected_session=session_id,
    )
