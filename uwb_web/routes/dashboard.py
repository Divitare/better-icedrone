"""Dashboard route — main landing page with live device cards."""

from flask import Blueprint, render_template
from uwb_web.services import session_service, device_service, measurement_service

bp = Blueprint('dashboard', __name__)


@bp.route('/')
def index():
    from uwb_web import get_serial_worker

    worker = get_serial_worker()
    active_session = session_service.get_active_session()
    devices = device_service.get_all_devices()

    live_data = worker.get_live_data() if worker else {}
    recent_values = worker.get_recent_values() if worker else {}
    stats = worker.stats if worker else {}

    # Per-device aggregate stats for the active session
    device_stats = {}
    if active_session:
        for row in measurement_service.get_device_stats(session_id=active_session.id):
            device_stats[row.device_id] = {
                'count': row.count,
                'min_range': round(row.min_range, 3) if row.min_range is not None else None,
                'max_range': round(row.max_range, 3) if row.max_range is not None else None,
                'avg_range': round(row.avg_range, 3) if row.avg_range is not None else None,
                'avg_rx_power': round(row.avg_rx_power, 1) if row.avg_rx_power is not None else None,
            }

    return render_template(
        'dashboard.html',
        active_session=active_session,
        devices=devices,
        live_data=live_data,
        recent_values=recent_values,
        stats=stats,
        device_stats=device_stats,
    )
