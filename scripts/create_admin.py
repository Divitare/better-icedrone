#!/usr/bin/env python3
"""Create or reset an admin user account."""

import sys
import os
import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uwb_web import create_app
from uwb_web.db import db
from uwb_web.models import User


# When invoked via "curl | sudo bash", stdin is the pipe,
# so interactive prompts must read from /dev/tty directly.
def _tty_input(prompt):
    """Read a line from /dev/tty (falls back to normal input)."""
    try:
        with open('/dev/tty', 'r') as tty:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            return tty.readline().rstrip('\n')
    except OSError:
        return input(prompt)


def _tty_getpass(prompt):
    """Read a password from /dev/tty without echo."""
    try:
        return getpass.getpass(prompt, stream=open('/dev/tty', 'w'))
    except OSError:
        return getpass.getpass(prompt)


def create_admin():
    app = create_app()
    with app.app_context():
        db.create_all()

        existing = User.query.count()
        if existing:
            print(f"  {existing} user(s) already exist.")
            answer = _tty_input("  Create another admin? [y/N]: ").strip().lower()
            if answer != 'y':
                print("  Cancelled.")
                return

        username = _tty_input("  Username: ").strip()
        if not username:
            print("  Error: username cannot be empty.")
            sys.exit(1)

        if User.query.filter_by(username=username).first():
            print(f"  Error: user '{username}' already exists.")
            sys.exit(1)

        password = _tty_getpass("  Password: ")
        if len(password) < 4:
            print("  Error: password must be at least 4 characters.")
            sys.exit(1)

        confirm = _tty_getpass("  Confirm password: ")
        if password != confirm:
            print("  Error: passwords do not match.")
            sys.exit(1)

        user = User(username=username, is_admin=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        print(f"  Admin user '{username}' created successfully.")


if __name__ == '__main__':
    create_admin()
