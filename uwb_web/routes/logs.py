"""Logs / history page with filtering and bulk actions."""

from flask import Blueprint, render_template, request, redirect, url_for
from datetime import datetime, timezone
from uwb_web.services import measurement_service, session_service, device_service
from uwb_web.models import RawLine, Event
from uwb_web.db import db

bp = Blueprint('logs', __name__)


@bp.route('/logs')
def index():
    tab = request.args.get('tab', 'measurements')
    session_id = request.args.get('session_id', type=int)
    device_id = request.args.get('device_id', type=int)
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    limit = request.args.get('limit', 200, type=int)

    start_dt = _try_iso(start)
    end_dt = _try_iso(end)

    measurements, raw_lines, events = [], [], []

    if tab == 'measurements':
        measurements = measurement_service.get_measurements_filtered(
            start=start_dt, end=end_dt, device_id=device_id,
            session_id=session_id, limit=limit,
        )
    elif tab == 'raw_lines':
        q = RawLine.query
        if start_dt:
            q = q.filter(RawLine.pi_received_at_utc >= start_dt)
        if end_dt:
            q = q.filter(RawLine.pi_received_at_utc <= end_dt)
        if session_id:
            q = q.filter_by(session_id=session_id)
        raw_lines = q.order_by(RawLine.pi_received_at_utc.desc()).limit(limit).all()
    elif tab == 'events':
        q = Event.query
        if start_dt:
            q = q.filter(Event.event_time_utc >= start_dt)
        if end_dt:
            q = q.filter(Event.event_time_utc <= end_dt)
        if session_id:
            q = q.filter_by(session_id=session_id)
        events = q.order_by(Event.event_time_utc.desc()).limit(limit).all()

    return render_template(
        'logs.html',
        tab=tab,
        measurements=measurements,
        raw_lines=raw_lines,
        events=events,
        sessions=session_service.get_all_sessions(),
        devices=device_service.get_all_devices(),
        selected_session=session_id,
        selected_device=device_id,
        start=start,
        end=end,
    )


@bp.route('/logs/delete', methods=['POST'])
def delete_logs():
    session_id = request.form.get('session_id', type=int)
    device_id = request.form.get('device_id', type=int)
    start_dt = _try_iso(request.form.get('start', ''))
    end_dt = _try_iso(request.form.get('end', ''))

    count = measurement_service.delete_measurements_filtered(
        start=start_dt, end=end_dt, device_id=device_id, session_id=session_id,
    )
    evt = Event(
        event_time_utc=datetime.now(timezone.utc),
        event_type='data_deleted',
        event_text=f'Deleted {count} measurements via UI',
    )
    db.session.add(evt)
    db.session.commit()
    return redirect(url_for('logs.index'))


@bp.route('/logs/clear-all', methods=['POST'])
def clear_all():
    if request.form.get('confirm', '') != 'DELETE ALL DATA':
        return redirect(url_for('logs.index'))
    measurement_service.clear_all_data()
    return redirect(url_for('logs.index'))


def _try_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
