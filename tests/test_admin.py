"""Tests for admin user-management routes."""

import unittest
import os
from uwb_web import create_app
from uwb_web.db import db
from uwb_web.models import User


class TestAdmin(unittest.TestCase):

    def setUp(self):
        os.environ['UWB_CONFIG'] = ''
        self.app = create_app(testing=True, db_uri='sqlite://')
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            # Create admin user
            admin = User(username='admin', is_admin=True)
            admin.set_password('adminpw')
            db.session.add(admin)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def _login(self, username='admin', password='adminpw'):
        return self.client.post('/login', data={
            'username': username, 'password': password,
        }, follow_redirects=True)

    # ----- Access control -----

    def test_admin_requires_login(self):
        resp = self.client.get('/admin/', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_admin_requires_admin_role(self):
        with self.app.app_context():
            user = User(username='regular', is_admin=False)
            user.set_password('pw1234')
            db.session.add(user)
            db.session.commit()
        self._login('regular', 'pw1234')
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 403)

    def test_admin_page_loads(self):
        self._login()
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'User Management', resp.data)

    # ----- Create user -----

    def test_create_user(self):
        self._login()
        resp = self.client.post('/admin/users/create', data={
            'username': 'newuser', 'password': 'pass1234',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'newuser', resp.data)
        with self.app.app_context():
            u = User.query.filter_by(username='newuser').first()
            self.assertIsNotNone(u)
            self.assertFalse(u.is_admin)

    def test_create_admin_user(self):
        self._login()
        self.client.post('/admin/users/create', data={
            'username': 'admin2', 'password': 'pass1234', 'is_admin': '1',
        }, follow_redirects=True)
        with self.app.app_context():
            u = User.query.filter_by(username='admin2').first()
            self.assertTrue(u.is_admin)

    def test_create_duplicate_user(self):
        self._login()
        resp = self.client.post('/admin/users/create', data={
            'username': 'admin', 'password': 'pass1234',
        }, follow_redirects=True)
        self.assertIn(b'already exists', resp.data)

    def test_create_user_short_password(self):
        self._login()
        resp = self.client.post('/admin/users/create', data={
            'username': 'shortpw', 'password': 'ab',
        }, follow_redirects=True)
        self.assertIn(b'at least 4', resp.data)

    # ----- Delete user -----

    def test_delete_user(self):
        self._login()
        with self.app.app_context():
            u = User(username='todelete')
            u.set_password('pass1234')
            db.session.add(u)
            db.session.commit()
            uid = u.id
        resp = self.client.post(f'/admin/users/{uid}/delete', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(username='todelete').first())

    def test_cannot_delete_self(self):
        self._login()
        with self.app.app_context():
            admin = User.query.filter_by(username='admin').first()
            admin_id = admin.id
        resp = self.client.post(f'/admin/users/{admin_id}/delete', follow_redirects=True)
        self.assertIn(b'cannot delete yourself', resp.data)

    # ----- Toggle admin -----

    def test_toggle_admin(self):
        self._login()
        with self.app.app_context():
            u = User(username='toggleme', is_admin=False)
            u.set_password('pass1234')
            db.session.add(u)
            db.session.commit()
            uid = u.id
        self.client.post(f'/admin/users/{uid}/toggle-admin', follow_redirects=True)
        with self.app.app_context():
            u = db.session.get(User, uid)
            self.assertTrue(u.is_admin)

    # ----- Reset password -----

    def test_reset_password(self):
        self._login()
        with self.app.app_context():
            u = User(username='pwreset')
            u.set_password('oldpass1')
            db.session.add(u)
            db.session.commit()
            uid = u.id
        resp = self.client.post(f'/admin/users/{uid}/reset-password',
                                data={'new_password': 'newpass1'},
                                follow_redirects=True)
        self.assertIn(b'Password reset', resp.data)
        with self.app.app_context():
            u = db.session.get(User, uid)
            self.assertTrue(u.check_password('newpass1'))


if __name__ == '__main__':
    unittest.main()
