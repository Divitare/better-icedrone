"""SQLAlchemy models for UWB Web application."""

from datetime import datetime, timezone
from uwb_web.db import db


def _utcnow():
    return datetime.now(timezone.utc)


class Session(db.Model):
    __tablename__ = 'sessions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    started_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)
    ended_at_utc = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)

    measurements = db.relationship('Measurement', backref='session', lazy='dynamic')
    events = db.relationship('Event', backref='session', lazy='dynamic')
    raw_lines = db.relationship('RawLine', backref='session', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'started_at_utc': self.started_at_utc.isoformat() if self.started_at_utc else None,
            'ended_at_utc': self.ended_at_utc.isoformat() if self.ended_at_utc else None,
            'is_active': self.is_active,
            'notes': self.notes,
        }


class Device(db.Model):
    __tablename__ = 'devices'

    id = db.Column(db.Integer, primary_key=True)
    short_addr_hex = db.Column(db.String(10), unique=True, nullable=False, index=True)
    short_addr_int = db.Column(db.Integer, nullable=True)
    label = db.Column(db.String(255), nullable=True)
    first_seen_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)
    last_seen_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)
    is_expected = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_anchor = db.Column(db.Boolean, default=False, nullable=False)
    x = db.Column(db.Float, nullable=True)
    y = db.Column(db.Float, nullable=True)
    z = db.Column(db.Float, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)

    measurements = db.relationship('Measurement', backref='device', lazy='dynamic')
    events = db.relationship('Event', backref='device', lazy='dynamic')

    @property
    def display_name(self):
        return self.label or self.short_addr_hex

    def to_dict(self):
        return {
            'id': self.id,
            'short_addr_hex': self.short_addr_hex,
            'short_addr_int': self.short_addr_int,
            'label': self.label,
            'display_name': self.display_name,
            'is_expected': self.is_expected,
            'is_active': self.is_active,
            'is_anchor': self.is_anchor,
            'x': self.x, 'y': self.y, 'z': self.z,
            'first_seen_at_utc': self.first_seen_at_utc.isoformat() if self.first_seen_at_utc else None,
            'last_seen_at_utc': self.last_seen_at_utc.isoformat() if self.last_seen_at_utc else None,
        }


class Measurement(db.Model):
    __tablename__ = 'measurements'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=True, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    pi_received_at_utc = db.Column(db.DateTime, nullable=False, index=True)
    range_m = db.Column(db.Float, nullable=False)
    rx_power_dbm = db.Column(db.Float, nullable=True)
    parse_source = db.Column(db.String(50), default='main_range_line')
    raw_line_id = db.Column(db.Integer, db.ForeignKey('raw_lines.id'), nullable=True)
    created_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.Index('ix_meas_session_device_time', 'session_id', 'device_id', 'pi_received_at_utc'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'device_id': self.device_id,
            'device_hex': self.device.short_addr_hex if self.device else None,
            'device_label': self.device.label if self.device else None,
            'pi_received_at_utc': self.pi_received_at_utc.isoformat() if self.pi_received_at_utc else None,
            'range_m': self.range_m,
            'rx_power_dbm': self.rx_power_dbm,
            'parse_source': self.parse_source,
        }


class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=True, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=True)
    event_time_utc = db.Column(db.DateTime, nullable=False, index=True)
    event_type = db.Column(db.String(100), nullable=False, index=True)
    event_text = db.Column(db.Text, nullable=True)
    raw_line_id = db.Column(db.Integer, db.ForeignKey('raw_lines.id'), nullable=True)
    created_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'device_id': self.device_id,
            'event_time_utc': self.event_time_utc.isoformat() if self.event_time_utc else None,
            'event_type': self.event_type,
            'event_text': self.event_text,
        }


class RawLine(db.Model):
    __tablename__ = 'raw_lines'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=True, index=True)
    pi_received_at_utc = db.Column(db.DateTime, nullable=False, index=True)
    line_text = db.Column(db.Text, nullable=False)
    line_type_guess = db.Column(db.String(50), nullable=True)
    parser_status = db.Column(db.String(50), nullable=False, default='unknown')
    created_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)


class AppConfig(db.Model):
    __tablename__ = 'app_config'

    key = db.Column(db.String(255), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)
