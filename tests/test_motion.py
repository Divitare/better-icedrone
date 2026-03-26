"""Tests for the motion control TCP client and routes."""

import unittest
import os
import json
import socket
import threading

from uwb_web import create_app
from uwb_web.db import db
from uwb_web.models import User
from uwb_web.services.motion_client import MotionClient


class FakeTCPServer:
    """Tiny TCP server that echoes JSON responses like the isel ApiServer."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(2)
        self.sock.settimeout(2.0)
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                client, _ = self.sock.accept()
                threading.Thread(target=self._handle, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle(self, client):
        buf = ''
        try:
            while True:
                data = client.recv(4096)
                if not data:
                    break
                buf += data.decode('utf-8')
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    req = json.loads(line)
                    cmd = req.get('cmd')
                    resp = {'status': 'ok', 'pos': {'x': 10.0, 'y': 20.0, 'z': 5.0}}
                    if cmd == 'get_status':
                        resp['state'] = {
                            'is_connected': True, 'is_busy': False,
                            'is_moving': False, 'is_grid_running': False,
                            'queue_size': 0, 'unfinished_tasks': 0,
                            'status_msg': 'Ready', 'pos': resp['pos'],
                        }
                    client.sendall((json.dumps(resp) + '\n').encode('utf-8'))
        except Exception:
            pass
        finally:
            client.close()

    def stop(self):
        self._running = False
        self.sock.close()
        self._thread.join(timeout=3)


class TestMotionClient(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = FakeTCPServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.client = MotionClient('127.0.0.1', self.server.port,
                                   connect_timeout=2.0, read_timeout=3.0)

    def tearDown(self):
        self.client.close()

    def test_get_status(self):
        r = self.client.get_status()
        self.assertEqual(r['status'], 'ok')
        self.assertIn('state', r)
        self.assertTrue(r['state']['is_connected'])

    def test_get_position(self):
        r = self.client.get_position()
        self.assertEqual(r['status'], 'ok')
        self.assertAlmostEqual(r['pos']['x'], 10.0)

    def test_move_absolute(self):
        r = self.client.move_absolute(100, 200, 50, speed=10)
        self.assertEqual(r['status'], 'ok')

    def test_move_relative(self):
        r = self.client.move_relative(5, -5, 0, speed=5)
        self.assertEqual(r['status'], 'ok')

    def test_stop(self):
        r = self.client.stop()
        self.assertEqual(r['status'], 'ok')

    def test_connection_refused(self):
        bad = MotionClient('127.0.0.1', 1, connect_timeout=0.5, read_timeout=1.0)
        with self.assertRaises(Exception):
            bad.get_status()
        bad.close()


class TestMotionRoutes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = FakeTCPServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        os.environ['UWB_CONFIG'] = ''
        self.app = create_app(testing=True, db_uri='sqlite://')
        # Override motion config to point to our fake server
        self.app.config['UWB']['motion'] = {
            'host': '127.0.0.1',
            'port': self.server.port,
            'connect_timeout': 2.0,
            'read_timeout': 3.0,
        }
        self.http = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            admin = User(username='admin', is_admin=True)
            admin.set_password('adminpw')
            db.session.add(admin)
            db.session.commit()
            # Seed DB config so _read_motion_cfg picks up the fake port
            from uwb_web.services.config_service import set_config
            set_config('motion_host', '127.0.0.1')
            set_config('motion_port', str(self.server.port))
            set_config('motion_connect_timeout', '2.0')
            set_config('motion_read_timeout', '3.0')
        self.http.post('/login', data={'username': 'admin', 'password': 'adminpw'})
        # Reset the lazy singleton for fresh client per test class
        import uwb_web.routes.motion as motion_mod
        motion_mod._reset_client()

    def tearDown(self):
        import uwb_web.routes.motion as motion_mod
        motion_mod._reset_client()
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_motion_page_loads(self):
        r = self.http.get('/motion/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Motion Control', r.data)

    def test_api_status(self):
        r = self.http.get('/motion/api/status')
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')

    def test_api_move_abs(self):
        r = self.http.post('/motion/api/move_abs',
                           json={'x': 10, 'y': 20, 'z': 0, 'speed': 5})
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')

    def test_api_stop(self):
        r = self.http.post('/motion/api/stop')
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')

    def test_get_connection_config(self):
        r = self.http.get('/motion/api/connection')
        data = r.get_json()
        self.assertEqual(data['host'], '127.0.0.1')
        self.assertEqual(data['port'], self.server.port)

    def test_set_connection_config(self):
        r = self.http.post('/motion/api/connection', json={
            'host': '192.168.1.50', 'port': 9999,
            'connect_timeout': 3.0, 'read_timeout': 15.0,
        })
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')
        # Verify it persisted
        r2 = self.http.get('/motion/api/connection')
        data2 = r2.get_json()
        self.assertEqual(data2['host'], '192.168.1.50')
        self.assertEqual(data2['port'], 9999)

    def test_set_connection_invalid_port(self):
        r = self.http.post('/motion/api/connection', json={
            'host': '10.0.0.1', 'port': 99999,
            'connect_timeout': 2.0, 'read_timeout': 10.0,
        })
        self.assertEqual(r.status_code, 400)


if __name__ == '__main__':
    unittest.main()
