"""Calibration page and JSON API — run calibration, view results, apply corrections."""

import json
import logging

from flask import Blueprint, render_template, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint('calibration', __name__, url_prefix='/calibration')

# Singleton runner — shared across requests
_runner = None


def _get_runner():
    global _runner
    if _runner is None:
        from flask import current_app
        from uwb_web.services.calibration import CalibrationRunner
        _runner = CalibrationRunner(current_app._get_current_object())
    return _runner


# ------------------------------------------------------------------
# Page
# ------------------------------------------------------------------

@bp.route('/')
def index():
    from uwb_web.services.config_service import get_config
    corrections_enabled = get_config('cal_corrections_enabled', 'false') == 'true'
    return render_template('calibration.html', corrections_enabled=corrections_enabled)


# ------------------------------------------------------------------
# Calibration run API
# ------------------------------------------------------------------

@bp.route('/api/start', methods=['POST'])
def api_start():
    data = request.get_json(silent=True) or {}

    # Origin in UWB metres — where the motion (0,0,0) sits in UWB space
    origin = {
        'x': float(data.get('origin_x', 0)),
        'y': float(data.get('origin_y', 0)),
        'z': float(data.get('origin_z', 0)),
    }
    dwell = float(data.get('dwell', 3.0))
    speed = float(data.get('speed', 10.0))
    name = data.get('name', '').strip() or None

    # Build grid points from axis config (in mm)
    grid_cfg = data.get('grid', {})
    grid_points = _build_grid(grid_cfg)

    if not grid_points:
        return jsonify({'status': 'error', 'msg': 'Grid produced no points.'}), 400

    runner = _get_runner()
    ok, msg = runner.start(
        grid_points=grid_points, origin=origin,
        dwell=dwell, speed=speed, name=name,
    )
    if not ok:
        return jsonify({'status': 'error', 'msg': msg}), 409
    return jsonify({'status': 'ok', 'msg': msg, 'run_id': runner.run_id})


@bp.route('/api/cancel', methods=['POST'])
def api_cancel():
    runner = _get_runner()
    if runner.cancel():
        return jsonify({'status': 'ok', 'msg': 'Cancelling…'})
    return jsonify({'status': 'error', 'msg': 'No calibration running.'}), 409


@bp.route('/api/status')
def api_status():
    runner = _get_runner()
    return jsonify({
        'status': runner.status,
        'progress': runner.progress,
        'run_id': runner.run_id,
    })


# ------------------------------------------------------------------
# Run history and details
# ------------------------------------------------------------------

@bp.route('/api/runs')
def api_runs():
    from uwb_web.models import CalibrationRun
    runs = CalibrationRun.query.order_by(CalibrationRun.id.desc()).limit(50).all()
    result = []
    for r in runs:
        result.append({
            'id': r.id,
            'name': r.name,
            'status': r.status,
            'created_at': r.created_at_utc.isoformat() if r.created_at_utc else None,
            'finished_at': r.finished_at_utc.isoformat() if r.finished_at_utc else None,
            'n_points': r.points.count(),
        })
    return jsonify(result)


@bp.route('/api/runs/<int:run_id>')
def api_run_detail(run_id):
    from uwb_web.models import CalibrationRun
    from uwb_web.db import db
    run = db.session.get(CalibrationRun, run_id)
    if not run:
        return jsonify({'status': 'error', 'msg': 'Run not found.'}), 404
    points = []
    for p in run.points.all():
        points.append({
            'index': p.point_index,
            'true_x': p.true_x, 'true_y': p.true_y, 'true_z': p.true_z,
            'uwb_x': p.uwb_x, 'uwb_y': p.uwb_y, 'uwb_z': p.uwb_z,
            'error_m': p.error_m,
            'ranges': json.loads(p.ranges_json) if p.ranges_json else {},
        })
    results = json.loads(run.results_json) if run.results_json else None
    return jsonify({
        'id': run.id,
        'name': run.name,
        'status': run.status,
        'origin': {'x': run.origin_x, 'y': run.origin_y, 'z': run.origin_z},
        'dwell_seconds': run.dwell_seconds,
        'speed_mm_s': run.speed_mm_s,
        'grid_config': json.loads(run.grid_config_json) if run.grid_config_json else None,
        'results': results,
        'points': points,
        'created_at': run.created_at_utc.isoformat() if run.created_at_utc else None,
        'finished_at': run.finished_at_utc.isoformat() if run.finished_at_utc else None,
    })


# ------------------------------------------------------------------
# Apply / toggle corrections
# ------------------------------------------------------------------

@bp.route('/api/apply', methods=['POST'])
def api_apply():
    """Save corrections from a specific run to the active config."""
    data = request.get_json(silent=True) or {}
    run_id = data.get('run_id')
    if not run_id:
        return jsonify({'status': 'error', 'msg': 'run_id required.'}), 400

    from uwb_web.models import CalibrationRun
    from uwb_web.db import db
    run = db.session.get(CalibrationRun, run_id)
    if not run or not run.results_json:
        return jsonify({'status': 'error', 'msg': 'Run not found or has no results.'}), 404

    results = json.loads(run.results_json)
    corrections = results.get('corrections', {})
    if not corrections:
        return jsonify({'status': 'error', 'msg': 'No corrections in this run.'}), 400

    from uwb_web.services.config_service import set_config
    from uwb_web.services.calibration import invalidate_corrections_cache
    set_config('cal_corrections', json.dumps(corrections))
    set_config('cal_corrections_enabled', 'true')
    invalidate_corrections_cache()

    logger.info('Applied corrections from run %d (%d anchors)', run_id, len(corrections))
    return jsonify({'status': 'ok', 'msg': f'Corrections applied from run {run_id}.'})


@bp.route('/api/toggle', methods=['POST'])
def api_toggle():
    """Enable or disable active corrections."""
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled', False))

    from uwb_web.services.config_service import set_config
    from uwb_web.services.calibration import invalidate_corrections_cache
    set_config('cal_corrections_enabled', 'true' if enabled else 'false')
    invalidate_corrections_cache()

    return jsonify({'status': 'ok', 'enabled': enabled})


@bp.route('/api/corrections')
def api_corrections():
    """Return currently active corrections and enabled state."""
    from uwb_web.services.config_service import get_config
    raw = get_config('cal_corrections')
    enabled = get_config('cal_corrections_enabled', 'false') == 'true'
    corrections = json.loads(raw) if raw else {}
    return jsonify({'enabled': enabled, 'corrections': corrections})


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_grid(cfg):
    """Build a list of grid points {'x': mm, 'y': mm, 'z': mm} from axis config."""
    def axis_values(axis_cfg):
        start = float(axis_cfg.get('start', 0))
        spacing = float(axis_cfg.get('spacing', 100))
        count = int(axis_cfg.get('count', 1))
        if count < 1:
            return []
        return [start + i * spacing for i in range(count)]

    x_cfg = cfg.get('x', {'start': 0, 'spacing': 100, 'count': 3})
    y_cfg = cfg.get('y', {'start': 0, 'spacing': 100, 'count': 3})
    z_cfg = cfg.get('z', {'start': 0, 'spacing': 0, 'count': 1})

    xs = axis_values(x_cfg)
    ys = axis_values(y_cfg)
    zs = axis_values(z_cfg)

    points = []
    for z in zs:
        for y in ys:
            for x in xs:
                points.append({'x': x, 'y': y, 'z': z})
    return points
