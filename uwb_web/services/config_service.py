"""Persistent app_config key-value store service."""

from datetime import datetime, timezone
from uwb_web.db import db
from uwb_web.models import AppConfig


def get_config(key, default=None):
    row = db.session.get(AppConfig, key)
    return row.value if row else default


def set_config(key, value):
    row = db.session.get(AppConfig, key)
    if row:
        row.value = str(value) if value is not None else None
        row.updated_at_utc = datetime.now(timezone.utc)
    else:
        row = AppConfig(
            key=key,
            value=str(value) if value is not None else None,
            updated_at_utc=datetime.now(timezone.utc),
        )
        db.session.add(row)
    db.session.commit()
    return row


def get_all_config():
    return {r.key: r.value for r in AppConfig.query.all()}


def set_defaults():
    """Populate default config values if they don't already exist."""
    defaults = {
        'serial_port': 'auto',
        'serial_baud': '115200',
        'store_raw_lines': 'true',
        'retention_days_raw': '30',
        'retention_days_measurements': '365',
        'motion_host': '127.0.0.1',
        'motion_port': '5001',
        'motion_connect_timeout': '2.0',
        'motion_read_timeout': '10.0',
    }
    for key, value in defaults.items():
        if not db.session.get(AppConfig, key):
            db.session.add(AppConfig(key=key, value=value, updated_at_utc=datetime.now(timezone.utc)))
    db.session.commit()
