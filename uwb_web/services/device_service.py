"""Device management service."""

from datetime import datetime, timezone
from uwb_web.db import db
from uwb_web.models import Device


def get_or_create_device(short_addr_hex, short_addr_int=None, now=None):
    """Get existing device by hex address or create a new one."""
    if now is None:
        now = datetime.now(timezone.utc)
    device = Device.query.filter_by(short_addr_hex=short_addr_hex).first()
    if device:
        device.last_seen_at_utc = now
        if short_addr_int is not None and device.short_addr_int is None:
            device.short_addr_int = short_addr_int
        return device
    device = Device(
        short_addr_hex=short_addr_hex,
        short_addr_int=short_addr_int,
        first_seen_at_utc=now,
        last_seen_at_utc=now,
    )
    db.session.add(device)
    db.session.flush()
    return device


def get_all_devices():
    return Device.query.order_by(Device.short_addr_hex).all()


def get_device_by_id(device_id):
    return db.session.get(Device, device_id)


def update_device(device_id, **kwargs):
    device = db.session.get(Device, device_id)
    if not device:
        return None
    allowed = ['label', 'is_expected', 'is_active', 'is_anchor', 'x', 'y', 'z', 'metadata_json']
    for key in allowed:
        if key in kwargs:
            setattr(device, key, kwargs[key])
    db.session.commit()
    return device
