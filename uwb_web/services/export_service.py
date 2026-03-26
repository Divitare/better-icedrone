"""CSV export service."""

import csv
import io
from uwb_web.models import Measurement, RawLine, Event, Device, Session
from uwb_web.db import db


def export_measurements_csv(start=None, end=None, device_id=None, session_id=None):
    q = db.session.query(Measurement, Device, Session).join(
        Device, Measurement.device_id == Device.id
    ).outerjoin(Session, Measurement.session_id == Session.id)

    if start:
        q = q.filter(Measurement.pi_received_at_utc >= start)
    if end:
        q = q.filter(Measurement.pi_received_at_utc <= end)
    if device_id:
        q = q.filter(Measurement.device_id == device_id)
    if session_id:
        q = q.filter(Measurement.session_id == session_id)
    q = q.order_by(Measurement.pi_received_at_utc)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'measurement_id', 'session_id', 'session_name', 'pi_received_at_utc',
        'short_addr_hex', 'device_label', 'range_m', 'rx_power_dbm',
        'parse_source', 'raw_line_id',
    ])
    for meas, device, session in q.all():
        writer.writerow([
            meas.id,
            meas.session_id,
            session.name if session else '',
            meas.pi_received_at_utc.isoformat() if meas.pi_received_at_utc else '',
            device.short_addr_hex,
            device.label or '',
            meas.range_m,
            meas.rx_power_dbm if meas.rx_power_dbm is not None else '',
            meas.parse_source,
            meas.raw_line_id or '',
        ])
    return output.getvalue()


def export_raw_lines_csv(start=None, end=None, session_id=None):
    q = RawLine.query
    if start:
        q = q.filter(RawLine.pi_received_at_utc >= start)
    if end:
        q = q.filter(RawLine.pi_received_at_utc <= end)
    if session_id:
        q = q.filter_by(session_id=session_id)
    q = q.order_by(RawLine.pi_received_at_utc)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'session_id', 'pi_received_at_utc', 'line_text', 'line_type_guess', 'parser_status'])
    for row in q.all():
        writer.writerow([
            row.id, row.session_id,
            row.pi_received_at_utc.isoformat() if row.pi_received_at_utc else '',
            row.line_text, row.line_type_guess, row.parser_status,
        ])
    return output.getvalue()


def export_events_csv(start=None, end=None, session_id=None):
    q = Event.query
    if start:
        q = q.filter(Event.event_time_utc >= start)
    if end:
        q = q.filter(Event.event_time_utc <= end)
    if session_id:
        q = q.filter_by(session_id=session_id)
    q = q.order_by(Event.event_time_utc)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'session_id', 'device_id', 'event_time_utc', 'event_type', 'event_text'])
    for row in q.all():
        writer.writerow([
            row.id, row.session_id, row.device_id,
            row.event_time_utc.isoformat() if row.event_time_utc else '',
            row.event_type, row.event_text,
        ])
    return output.getvalue()
