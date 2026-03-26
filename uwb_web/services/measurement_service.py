"""Measurement query and management service."""

from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from uwb_web.db import db
from uwb_web.models import Measurement


def get_recent_measurements(limit=100, device_id=None, session_id=None):
    q = Measurement.query
    if device_id:
        q = q.filter_by(device_id=device_id)
    if session_id:
        q = q.filter_by(session_id=session_id)
    return q.order_by(Measurement.pi_received_at_utc.desc()).limit(limit).all()


def get_measurements_filtered(start=None, end=None, device_id=None, session_id=None, limit=10000):
    q = Measurement.query
    if start:
        q = q.filter(Measurement.pi_received_at_utc >= start)
    if end:
        q = q.filter(Measurement.pi_received_at_utc <= end)
    if device_id:
        q = q.filter_by(device_id=device_id)
    if session_id:
        q = q.filter_by(session_id=session_id)
    return q.order_by(Measurement.pi_received_at_utc.desc()).limit(limit).all()


def get_device_stats(session_id=None, window_minutes=5):
    """Per-device aggregate stats over a recent time window."""
    window_start = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    q = db.session.query(
        Measurement.device_id,
        func.count(Measurement.id).label('count'),
        func.min(Measurement.range_m).label('min_range'),
        func.max(Measurement.range_m).label('max_range'),
        func.avg(Measurement.range_m).label('avg_range'),
        func.min(Measurement.rx_power_dbm).label('min_rx_power'),
        func.max(Measurement.rx_power_dbm).label('max_rx_power'),
        func.avg(Measurement.rx_power_dbm).label('avg_rx_power'),
    ).filter(Measurement.pi_received_at_utc >= window_start)
    if session_id:
        q = q.filter(Measurement.session_id == session_id)
    return q.group_by(Measurement.device_id).all()


def get_measurement_count(session_id=None, device_id=None):
    q = Measurement.query
    if session_id:
        q = q.filter_by(session_id=session_id)
    if device_id:
        q = q.filter_by(device_id=device_id)
    return q.count()


def delete_measurements_filtered(start=None, end=None, device_id=None, session_id=None):
    q = Measurement.query
    if start:
        q = q.filter(Measurement.pi_received_at_utc >= start)
    if end:
        q = q.filter(Measurement.pi_received_at_utc <= end)
    if device_id:
        q = q.filter_by(device_id=device_id)
    if session_id:
        q = q.filter_by(session_id=session_id)
    count = q.delete(synchronize_session='fetch')
    db.session.commit()
    return count


def clear_all_data():
    """Delete ALL measurements, events, raw lines, and sessions."""
    from uwb_web.models import Event, RawLine, Session
    Measurement.query.delete()
    Event.query.delete()
    RawLine.query.delete()
    Session.query.delete()
    db.session.commit()
