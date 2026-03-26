"""System diagnostics page."""

import os
from flask import Blueprint, render_template, current_app
from uwb_web.models import Event, RawLine, Measurement
from uwb_web import __version__

bp = Blueprint('system', __name__)


@bp.route('/system')
def index():
    from uwb_web import get_serial_worker, get_sse_broadcaster

    worker = get_serial_worker()
    broadcaster = get_sse_broadcaster()
    stats = worker.stats if worker else {}

    events = Event.query.order_by(Event.event_time_utc.desc()).limit(50).all()
    unknown = (
        RawLine.query.filter_by(parser_status='unknown')
        .order_by(RawLine.pi_received_at_utc.desc()).limit(30).all()
    )

    config = current_app.config.get('UWB', {})
    db_path = os.path.abspath(config.get('database', {}).get('path', 'data/uwb_data.db'))
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    return render_template(
        'system.html',
        stats=stats,
        events=events,
        unknown_lines=unknown,
        db_size=db_size,
        db_path=db_path,
        meas_count=Measurement.query.count(),
        event_count=Event.query.count(),
        raw_count=RawLine.query.count(),
        sse_clients=broadcaster.client_count if broadcaster else 0,
        version=__version__,
    )
