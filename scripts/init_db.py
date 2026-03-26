#!/usr/bin/env python3
"""Initialize database and seed default config values."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uwb_web import create_app
from uwb_web.db import db
from uwb_web.services.config_service import set_defaults

app = create_app()

with app.app_context():
    db.create_all()
    set_defaults()
    print("Database initialized successfully.")
    print(f"  Location: {app.config['SQLALCHEMY_DATABASE_URI']}")
