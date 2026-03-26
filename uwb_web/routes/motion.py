"""Motion control page and JSON API for the isel iMC-S8 controller."""

from flask import Blueprint, render_template, jsonify, request
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('motion', __name__, url_prefix='/motion')

# Lazy singleton — recreated when connection settings change
_client = None


def _read_motion_cfg():
    """Read motion connection settings from DB, fall back to config.yaml."""
    from uwb_web.services.config_service import get_config
    from flask import current_app
    yaml_cfg = current_app.config.get('UWB', {}).get('motion', {})
    return {
        'host': get_config('motion_host') or yaml_cfg.get('host', '127.0.0.1'),
        'port': int(get_config('motion_port') or yaml_cfg.get('port', 5001)),
        'connect_timeout': float(get_config('motion_connect_timeout') or yaml_cfg.get('connect_timeout', 2.0)),
        'read_timeout': float(get_config('motion_read_timeout') or yaml_cfg.get('read_timeout', 10.0)),
    }


def _get_client():
    global _client
    if _client is None:
        cfg = _read_motion_cfg()
        from uwb_web.services.motion_client import MotionClient
        _client = MotionClient(
            host=cfg['host'], port=cfg['port'],
            connect_timeout=cfg['connect_timeout'],
            read_timeout=cfg['read_timeout'],
        )
    return _client


def _reset_client():
    """Close and discard the current client so the next call picks up new settings."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def _proxy(fn, *args, **kwargs):
    """Call a MotionClient method and return a JSON response."""
    try:
        result = fn(*args, **kwargs)
        return jsonify(result)
    except (ConnectionRefusedError, ConnectionError, OSError) as e:
        return jsonify({'status': 'error', 'msg': 'Motion controller not reachable. Is the isel controller running?'}), 502
    except Exception as e:
        logger.exception('Motion API error')
        return jsonify({'status': 'error', 'msg': str(e)}), 500


# ------------------------------------------------------------------
# Page
# ------------------------------------------------------------------

@bp.route('/')
def index():
    cfg = _read_motion_cfg()
    return render_template('motion.html', motion_cfg=cfg)


# ------------------------------------------------------------------
# JSON API endpoints
# ------------------------------------------------------------------

@bp.route('/api/status')
def api_status():
    return _proxy(_get_client().get_status)


@bp.route('/api/position')
def api_position():
    return _proxy(_get_client().get_position)


@bp.route('/api/init', methods=['POST'])
def api_init():
    return _proxy(_get_client().init_axes, wait=True)


@bp.route('/api/home', methods=['POST'])
def api_home():
    data = request.get_json(silent=True) or {}
    speed = float(data.get('speed', 12.5))
    return _proxy(_get_client().home, speed=speed, wait=True)


@bp.route('/api/move_abs', methods=['POST'])
def api_move_abs():
    data = request.get_json(silent=True) or {}
    x = float(data.get('x', 0))
    y = float(data.get('y', 0))
    z = float(data.get('z', 0))
    speed = float(data.get('speed', 5.0))
    wait = bool(data.get('wait', False))
    return _proxy(_get_client().move_absolute, x, y, z, speed=speed, wait=wait)


@bp.route('/api/move_rel', methods=['POST'])
def api_move_rel():
    data = request.get_json(silent=True) or {}
    x = float(data.get('x', 0))
    y = float(data.get('y', 0))
    z = float(data.get('z', 0))
    speed = float(data.get('speed', 5.0))
    wait = bool(data.get('wait', False))
    return _proxy(_get_client().move_relative, x, y, z, speed=speed, wait=wait)


@bp.route('/api/stop', methods=['POST'])
def api_stop():
    return _proxy(_get_client().stop)


@bp.route('/api/set_accel', methods=['POST'])
def api_set_accel():
    data = request.get_json(silent=True) or {}
    accel = float(data.get('accel', 1000))
    return _proxy(_get_client().set_acceleration, accel)


@bp.route('/api/grid', methods=['POST'])
def api_grid():
    data = request.get_json(silent=True) or {}
    return _proxy(_get_client().start_grid, data)


# ------------------------------------------------------------------
# Connection settings (stored in DB)
# ------------------------------------------------------------------

@bp.route('/api/connection', methods=['GET'])
def api_get_connection():
    return jsonify(_read_motion_cfg())


@bp.route('/api/connection', methods=['POST'])
def api_set_connection():
    from uwb_web.services.config_service import set_config
    data = request.get_json(silent=True) or {}

    host = data.get('host', '').strip()
    port = data.get('port')
    connect_timeout = data.get('connect_timeout')
    read_timeout = data.get('read_timeout')

    if not host:
        return jsonify({'status': 'error', 'msg': 'Host is required.'}), 400
    try:
        port = int(port)
        if not (1 <= port <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'msg': 'Port must be 1-65535.'}), 400
    try:
        connect_timeout = float(connect_timeout)
        read_timeout = float(read_timeout)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'msg': 'Timeouts must be numbers.'}), 400

    set_config('motion_host', host)
    set_config('motion_port', str(port))
    set_config('motion_connect_timeout', str(connect_timeout))
    set_config('motion_read_timeout', str(read_timeout))

    _reset_client()
    logger.info('Motion connection updated: %s:%d', host, port)
    return jsonify({'status': 'ok', 'msg': f'Connection updated to {host}:{port}'})
