"""Basic model and database tests."""

import unittest
import os

from uwb_web import create_app
from uwb_web.db import db
from uwb_web.models import Session, Device, Measurement, Event, RawLine, AppConfig


class TestModels(unittest.TestCase):

    def setUp(self):
        os.environ['UWB_CONFIG'] = ''  # skip config file
        self.app = create_app(
            testing=True,
            db_uri='sqlite://',  # in-memory for speed and no file-lock issues
        )
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_create_session(self):
        with self.app.app_context():
            s = Session(name='Test', started_at_utc=datetime.now(timezone.utc))
            db.session.add(s)
            db.session.commit()
            self.assertIsNotNone(s.id)
            self.assertTrue(s.is_active)

    def test_create_device(self):
        with self.app.app_context():
            d = Device(short_addr_hex='1786', short_addr_int=0x1786)
            db.session.add(d)
            db.session.commit()
            self.assertEqual(d.short_addr_hex, '1786')
            self.assertEqual(d.display_name, '1786')
            d.label = 'Anchor1'
            db.session.commit()
            self.assertEqual(d.display_name, 'Anchor1')

    def test_create_measurement(self):
        with self.app.app_context():
            s = Session(name='S1', started_at_utc=datetime.now(timezone.utc))
            d = Device(short_addr_hex='2A3F')
            db.session.add_all([s, d])
            db.session.flush()
            m = Measurement(
                session_id=s.id, device_id=d.id,
                pi_received_at_utc=datetime.now(timezone.utc),
                range_m=3.15, rx_power_dbm=-78.5,
            )
            db.session.add(m)
            db.session.commit()
            self.assertIsNotNone(m.id)
            self.assertEqual(m.device.short_addr_hex, '2A3F')

    def test_app_config(self):
        with self.app.app_context():
            c = AppConfig(key='test_key', value='test_value', updated_at_utc=datetime.now(timezone.utc))
            db.session.add(c)
            db.session.commit()
            row = db.session.get(AppConfig, 'test_key')
            self.assertEqual(row.value, 'test_value')

    def test_session_service(self):
        with self.app.app_context():
            from uwb_web.services.session_service import create_session, get_active_session, end_session
            s = create_session('My Session')
            self.assertTrue(s.is_active)
            active = get_active_session()
            self.assertEqual(active.id, s.id)
            end_session(s.id)
            active = get_active_session()
            self.assertIsNone(active)

    def test_device_service(self):
        with self.app.app_context():
            from uwb_web.services.device_service import get_or_create_device, get_all_devices
            d = get_or_create_device('ABCD', 0xABCD)
            db.session.commit()
            self.assertEqual(d.short_addr_hex, 'ABCD')
            all_devs = get_all_devices()
            self.assertEqual(len(all_devs), 1)
            # Get same device again
            d2 = get_or_create_device('ABCD')
            self.assertEqual(d.id, d2.id)


if __name__ == '__main__':
    unittest.main()
