"""Session management service."""

from datetime import datetime, timezone
from uwb_web.db import db
from uwb_web.models import Session


def get_active_session():
    return Session.query.filter_by(is_active=True).order_by(Session.started_at_utc.desc()).first()


def create_session(name=None):
    """Create a new logging session. Ends any currently active session first."""
    now = datetime.now(timezone.utc)
    if name is None:
        name = f"Session {now.strftime('%Y-%m-%d %H:%M:%S')}"
    # End currently active sessions
    for s in Session.query.filter_by(is_active=True).all():
        s.is_active = False
        s.ended_at_utc = now
    session = Session(name=name, started_at_utc=now, is_active=True)
    db.session.add(session)
    db.session.commit()
    return session


def end_session(session_id):
    session = db.session.get(Session, session_id)
    if session and session.is_active:
        session.is_active = False
        session.ended_at_utc = datetime.now(timezone.utc)
        db.session.commit()
    return session


def get_all_sessions():
    return Session.query.order_by(Session.started_at_utc.desc()).all()


def get_session_by_id(session_id):
    return db.session.get(Session, session_id)


def rename_session(session_id, name):
    session = db.session.get(Session, session_id)
    if session:
        session.name = name
        db.session.commit()
    return session


def update_session_notes(session_id, notes):
    session = db.session.get(Session, session_id)
    if session:
        session.notes = notes
        db.session.commit()
    return session


def delete_session(session_id):
    """Delete a session and all associated data."""
    from uwb_web.models import Measurement, Event, RawLine
    session = db.session.get(Session, session_id)
    if not session:
        return False
    Measurement.query.filter_by(session_id=session_id).delete()
    Event.query.filter_by(session_id=session_id).delete()
    RawLine.query.filter_by(session_id=session_id).delete()
    db.session.delete(session)
    db.session.commit()
    return True
