"""UWB Web — Flask application factory and global singletons."""

import os
import logging

__version__ = '1.0.0'

_serial_worker = None
_sse_broadcaster = None


def get_serial_worker():
    return _serial_worker


def get_sse_broadcaster():
    return _sse_broadcaster


def create_app(config_path=None, testing=False, db_uri=None):
    global _serial_worker, _sse_broadcaster

    from flask import Flask
    from uwb_web.config import load_config
    from uwb_web.db import db
    from uwb_web.sse import SSEBroadcaster

    app = Flask(__name__)
    config = load_config(config_path)
    app.config['UWB'] = config
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uwb-dev-key-change-in-prod')
    if testing:
        app.config['TESTING'] = True

    # --- Database ---
    if db_uri:
        app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    else:
        db_path = os.path.abspath(config['database']['path'])
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'timeout': 15},
        'pool_pre_ping': True,
    }
    db.init_app(app)

    with app.app_context():
        from uwb_web import models  # noqa: F401
        db.create_all()
        # Enable WAL mode for better read/write concurrency
        with db.engine.connect() as conn:
            conn.execute(db.text('PRAGMA journal_mode=WAL'))
            conn.execute(db.text('PRAGMA busy_timeout=5000'))
            conn.commit()
        # Seed default config values
        from uwb_web.services.config_service import set_defaults
        set_defaults()

    # --- Logging ---
    log_level = getattr(logging, config['logging']['level'].upper(), logging.INFO)
    log_file = config['logging'].get('file')
    handlers = [logging.StreamHandler()]
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        handlers=handlers,
    )

    # --- Blueprints ---
    from uwb_web.routes.dashboard import bp as dashboard_bp
    from uwb_web.routes.measurements import bp as measurements_bp
    from uwb_web.routes.sessions import bp as sessions_bp
    from uwb_web.routes.devices import bp as devices_bp
    from uwb_web.routes.logs import bp as logs_bp
    from uwb_web.routes.system import bp as system_bp
    from uwb_web.routes.api import bp as api_bp
    from uwb_web.routes.export import bp as export_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(measurements_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(export_bp)

    # --- Template globals ---
    @app.context_processor
    def inject_globals():
        from uwb_web.services.session_service import get_active_session
        return {
            'app_version': __version__,
            'active_session_global': get_active_session(),
        }

    # --- Serial worker ---
    # Only start in the actual serving process, not in Werkzeug's reloader parent.
    if not app.config.get('TESTING'):
        is_reloader_parent = (
            config['web'].get('debug', False)
            and os.environ.get('WERKZEUG_RUN_MAIN') != 'true'
        )
        if not is_reloader_parent:
            from uwb_web.serial_worker import SerialWorker
            _sse_broadcaster = SSEBroadcaster()
            _serial_worker = SerialWorker(app, config)
            _serial_worker.sse_broadcaster = _sse_broadcaster
            _serial_worker.start()

    return app
