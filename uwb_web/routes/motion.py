"""Motion control page and JSON API for the isel iMC-S8 controller."""

from flask import Blueprint, render_template, jsonify, request
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('motion', __name__, url_prefix='/motion')

# Lazy singleton — created on first use from app config
_client = None


def _get_client():
    global _client
    if _client is None:
        from flask import current_app
        cfg = current_app.config.get('UWB', {}).get('motion', {})
        host = cfg.get('host', '127.0.0.1')
        port = cfg.get('port', 5000)
        timeout = cfg.get('timeout', 10.0)
        from uwb_web.services.motion_client import MotionClient
        _client = MotionClient(host=host, port=port, timeout=timeout)
    return _client


def _proxy(fn, *args, **kwargs):
    """Call a MotionClient method and return a JSON response."""
    try:
        result = fn(*args, **kwargs)
        return jsonify(result)
    except ConnectionRefusedError:
        return jsonify({'status': 'error', 'msg': 'Motion controller not reachable. Is the isel controller running?'}), 502
    except Exception as e:
        logger.exception('Motion API error')
        return jsonify({'status': 'error', 'msg': str(e)}), 500


# ------------------------------------------------------------------
# Page
# ------------------------------------------------------------------

@bp.route('/')
def index():
    return render_template('motion.html')


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
