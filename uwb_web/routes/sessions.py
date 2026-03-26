"""Sessions management page."""

from flask import Blueprint, render_template, request, redirect, url_for
from sqlalchemy import func
from uwb_web.services import session_service
from uwb_web.db import db
from uwb_web.models import Measurement

bp = Blueprint('sessions', __name__)


@bp.route('/sessions')
def index():
    sessions = session_service.get_all_sessions()
    session_data = []
    for s in sessions:
        mcount = s.measurements.count()
        dcount = (
            db.session.query(func.count(func.distinct(Measurement.device_id)))
            .filter_by(session_id=s.id).scalar()
        ) or 0
        duration = None
        if s.started_at_utc and s.ended_at_utc:
            duration = s.ended_at_utc - s.started_at_utc
        session_data.append({
            'session': s,
            'measurement_count': mcount,
            'device_count': dcount,
            'duration': duration,
        })
    return render_template('sessions.html', session_data=session_data)


@bp.route('/sessions/create', methods=['POST'])
def create():
    name = request.form.get('name', '').strip() or None
    session = session_service.create_session(name=name)
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.start_logging(session.id)
    return redirect(url_for('sessions.index'))


@bp.route('/sessions/<int:session_id>/end', methods=['POST'])
def end(session_id):
    session_service.end_session(session_id)
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker and worker.current_session_id == session_id:
        worker.stop_logging()
    return redirect(url_for('sessions.index'))


@bp.route('/sessions/<int:session_id>/rename', methods=['POST'])
def rename(session_id):
    name = request.form.get('name', '').strip()
    if name:
        session_service.rename_session(session_id, name)
    return redirect(url_for('sessions.index'))


@bp.route('/sessions/<int:session_id>/notes', methods=['POST'])
def notes(session_id):
    session_service.update_session_notes(session_id, request.form.get('notes', ''))
    return redirect(url_for('sessions.index'))


@bp.route('/sessions/<int:session_id>/delete', methods=['POST'])
def delete(session_id):
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker and worker.current_session_id == session_id:
        worker.stop_logging()
    session_service.delete_session(session_id)
    return redirect(url_for('sessions.index'))
