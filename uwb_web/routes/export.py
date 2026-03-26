"""CSV export endpoints."""

from flask import Blueprint, request, Response
from datetime import datetime
from uwb_web.services import export_service

bp = Blueprint('export', __name__, url_prefix='/export')


def _try_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


@bp.route('/measurements')
def measurements_csv():
    csv_data = export_service.export_measurements_csv(
        start=_try_iso(request.args.get('start')),
        end=_try_iso(request.args.get('end')),
        device_id=request.args.get('device_id', type=int),
        session_id=request.args.get('session_id', type=int),
    )
    return Response(
        csv_data, mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=measurements.csv'},
    )


@bp.route('/raw_lines')
def raw_lines_csv():
    csv_data = export_service.export_raw_lines_csv(
        start=_try_iso(request.args.get('start')),
        end=_try_iso(request.args.get('end')),
        session_id=request.args.get('session_id', type=int),
    )
    return Response(
        csv_data, mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=raw_lines.csv'},
    )


@bp.route('/events')
def events_csv():
    csv_data = export_service.export_events_csv(
        start=_try_iso(request.args.get('start')),
        end=_try_iso(request.args.get('end')),
        session_id=request.args.get('session_id', type=int),
    )
    return Response(
        csv_data, mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=events.csv'},
    )
