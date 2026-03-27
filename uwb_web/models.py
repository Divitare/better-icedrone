"""SQLAlchemy models for UWB Web application."""

from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
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


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class CalibrationRun(db.Model):
    """A calibration run that moves the tag to known positions and collects data."""
    __tablename__ = 'calibration_runs'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='running')  # running, completed, failed, cancelled
    created_at_utc = db.Column(db.DateTime, nullable=False, default=_utcnow)
    finished_at_utc = db.Column(db.DateTime, nullable=True)

    # Coordinate mapping: true_uwb = motion_mm / 1000 + origin
    origin_x = db.Column(db.Float, nullable=False, default=0.0)
    origin_y = db.Column(db.Float, nullable=False, default=0.0)
    origin_z = db.Column(db.Float, nullable=False, default=0.0)

    dwell_seconds = db.Column(db.Float, nullable=False, default=3.0)
    speed_mm_s = db.Column(db.Float, nullable=False, default=10.0)

    # JSON blobs for config and results
    grid_config_json = db.Column(db.Text, nullable=True)
    results_json = db.Column(db.Text, nullable=True)

    points = db.relationship('CalibrationPoint', backref='run',
                             cascade='all, delete-orphan', lazy='dynamic',
                             order_by='CalibrationPoint.point_index')


class CalibrationPoint(db.Model):
    """One measured point in a calibration run."""
    __tablename__ = 'calibration_points'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('calibration_runs.id'), nullable=False, index=True)
    point_index = db.Column(db.Integer, nullable=False)

    # True position in UWB coordinates (metres)
    true_x = db.Column(db.Float, nullable=False)
    true_y = db.Column(db.Float, nullable=False)
    true_z = db.Column(db.Float, nullable=False, default=0.0)

    # Mean UWB estimated position during dwell
    uwb_x = db.Column(db.Float, nullable=True)
    uwb_y = db.Column(db.Float, nullable=True)
    uwb_z = db.Column(db.Float, nullable=True)

    # Per-anchor collected ranges: {anchor_hex: {mean, std, count, device_id}}
    ranges_json = db.Column(db.Text, nullable=True)

    error_m = db.Column(db.Float, nullable=True)   # Euclidean distance to true position
    collected_at_utc = db.Column(db.DateTime, nullable=True)
