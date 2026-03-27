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

    # Reload engine weights so live corrections take effect immediately
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.reload_engine()

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

    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.reload_engine()

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
# Engine settings (EKF / NLOS / smoother)
# ------------------------------------------------------------------

_ENGINE_DEFAULTS = {
    'ekf_enabled': True,
    'nlos_enabled': True,
    'nlos_threshold': 0.5,
    'process_noise': 0.1,
    'range_var': 0.1,
    'tag_z': 0.0,
}


@bp.route('/api/engine', methods=['GET'])
def api_engine_get():
    """Return current engine settings."""
    from uwb_web.services.config_service import get_config
    raw = get_config('engine_settings')
    cfg = json.loads(raw) if raw else dict(_ENGINE_DEFAULTS)
    return jsonify(cfg)


@bp.route('/api/engine', methods=['POST'])
def api_engine_set():
    """Save engine settings and reload the live engine."""
    data = request.get_json(silent=True) or {}
    cfg = {
        'ekf_enabled': bool(data.get('ekf_enabled', True)),
        'nlos_enabled': bool(data.get('nlos_enabled', True)),
        'nlos_threshold': float(data.get('nlos_threshold', 0.5)),
        'process_noise': float(data.get('process_noise', 0.1)),
        'range_var': float(data.get('range_var', 0.1)),
        'tag_z': float(data.get('tag_z', 0.0)),
    }
    from uwb_web.services.config_service import set_config
    set_config('engine_settings', json.dumps(cfg))

    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.reload_engine()

    return jsonify({'status': 'ok', **cfg})


@bp.route('/api/engine/reset', methods=['POST'])
def api_engine_reset():
    """Reset the EKF state (e.g. after moving the tag by hand)."""
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.get_engine().reset()
    return jsonify({'status': 'ok', 'msg': 'EKF state reset.'})


# ------------------------------------------------------------------
# Trajectory smoother ("deblur")
# ------------------------------------------------------------------

@bp.route('/api/smooth', methods=['POST'])
def api_smooth():
    """
    Apply the RTS trajectory smoother to a set of positions.

    Body: { "positions": [...], "process_noise": 0.1, "measurement_noise": 0.01, "dt": 0.1 }
      or: { "source": "history" }   — smooth the live position history buffer
      or: { "source": "run", "run_id": 123 }  — smooth a calibration run's points
    """
    from uwb_web.services.position_engine import smooth_trajectory

    data = request.get_json(silent=True) or {}
    pn = float(data.get('process_noise', 0.1))
    mn = float(data.get('measurement_noise', 0.01))
    dt = float(data.get('dt', 0.1))

    source = data.get('source', 'positions')

    if source == 'history':
        from uwb_web import get_serial_worker
        worker = get_serial_worker()
        if not worker:
            return jsonify({'status': 'error', 'msg': 'No serial worker.'}), 503
        pos_data = worker.get_position()
        positions = pos_data.get('history', [])
    elif source == 'run':
        run_id = data.get('run_id')
        if not run_id:
            return jsonify({'status': 'error', 'msg': 'run_id required.'}), 400
        from uwb_web.models import CalibrationRun
        from uwb_web.db import db
        run = db.session.get(CalibrationRun, run_id)
        if not run:
            return jsonify({'status': 'error', 'msg': 'Run not found.'}), 404
        positions = []
        for p in run.points.order_by('point_index').all():
            if p.uwb_x is not None:
                positions.append({
                    'x': p.uwb_x, 'y': p.uwb_y,
                    'true_x': p.true_x, 'true_y': p.true_y,
                })
    else:
        positions = data.get('positions', [])

    if len(positions) < 3:
        return jsonify({'status': 'error', 'msg': 'Need at least 3 positions.'}), 400

    smoothed = smooth_trajectory(positions, dt=dt,
                                 process_noise=pn, measurement_noise=mn)
    return jsonify({'status': 'ok', 'positions': smoothed, 'n': len(smoothed)})


# ------------------------------------------------------------------
# Coordinate-frame alignment & anchor refinement
# ------------------------------------------------------------------

@bp.route('/api/auto-origin', methods=['POST'])
def api_auto_origin():
    """
    Estimate the rigid transform (rotation + translation + scale) from
    motion-controller coordinates to UWB room coordinates.

    Uses a completed calibration run's grid points (mm, precise relative
    positions from the motion controller) and the UWB-estimated positions
    at each grid point.

    Body: { "run_id": int }
    """
    from uwb_web.models import CalibrationRun
    from uwb_web.db import db
    from uwb_web.services.calibration import estimate_rigid_transform

    data = request.get_json(silent=True) or {}
    run_id = data.get('run_id')
    if not run_id:
        return jsonify({'status': 'error', 'msg': 'run_id required.'}), 400

    run = db.session.get(CalibrationRun, run_id)
    if not run:
        return jsonify({'status': 'error', 'msg': 'Run not found.'}), 404

    grid = json.loads(run.grid_config_json) if run.grid_config_json else []
    points = run.points.all()

    # Build matching pairs: motion mm → UWB metres
    motion_mm = []
    uwb_m = []
    for p in points:
        if p.uwb_x is None:
            continue
        if p.point_index >= len(grid):
            continue
        gp = grid[p.point_index]
        motion_mm.append([gp['x'], gp['y']])
        uwb_m.append([p.uwb_x, p.uwb_y])

    if len(motion_mm) < 3:
        return jsonify({'status': 'error',
                        'msg': 'Need at least 3 points with UWB data.'}), 400

    result = estimate_rigid_transform(motion_mm, uwb_m)
    if result is None:
        return jsonify({'status': 'error', 'msg': 'Transform estimation failed.'}), 500

    # Save transform to config for use in future calibration runs
    from uwb_web.services.config_service import set_config
    transform = {
        'R': result['R'],
        't': result['t'],
        'scale': result['scale'],
        'rotation_deg': result['rotation_deg'],
        'source_run_id': run_id,
    }
    set_config('coordinate_transform', json.dumps(transform))

    return jsonify({'status': 'ok', **result})


@bp.route('/api/auto-origin', methods=['GET'])
def api_auto_origin_get():
    """Return the stored coordinate transform (if any)."""
    from uwb_web.services.config_service import get_config
    raw = get_config('coordinate_transform')
    if not raw:
        return jsonify({'status': 'none', 'msg': 'No transform computed yet.'})
    return jsonify({'status': 'ok', **json.loads(raw)})


@bp.route('/api/refine-anchors', methods=['POST'])
def api_refine_anchors():
    """
    Refine anchor positions using calibration data.

    Uses the precise tag positions (from the motion controller, transformed
    to UWB space via the rigid transform) and per-anchor range measurements
    from a calibration run.

    Body: { "run_id": int }
    """
    from uwb_web.models import CalibrationRun, Device
    from uwb_web.db import db
    from uwb_web.services.calibration import (
        estimate_rigid_transform, refine_anchor_positions,
    )

    data = request.get_json(silent=True) or {}
    run_id = data.get('run_id')
    if not run_id:
        return jsonify({'status': 'error', 'msg': 'run_id required.'}), 400

    run = db.session.get(CalibrationRun, run_id)
    if not run:
        return jsonify({'status': 'error', 'msg': 'Run not found.'}), 404

    grid = json.loads(run.grid_config_json) if run.grid_config_json else []
    points = run.points.all()

    # Step 1: Compute rigid transform from this run's data
    motion_mm = []
    uwb_m = []
    range_data_list = []

    for p in points:
        if p.uwb_x is None:
            continue
        if p.point_index >= len(grid):
            continue
        gp = grid[p.point_index]
        motion_mm.append([gp['x'], gp['y']])
        uwb_m.append([p.uwb_x, p.uwb_y])
        rd = json.loads(p.ranges_json) if p.ranges_json else {}
        # Convert hex-keyed ranges to device_id-keyed
        rd_by_id = {}
        for hex_addr, info in rd.items():
            did = info.get('device_id')
            if did is not None:
                rd_by_id[did] = {'mean': info['mean'], 'weight': 1.0}
        range_data_list.append(rd_by_id)

    if len(motion_mm) < 3:
        return jsonify({'status': 'error',
                        'msg': 'Need at least 3 points with UWB data.'}), 400

    transform = estimate_rigid_transform(motion_mm, uwb_m)
    if transform is None:
        return jsonify({'status': 'error',
                        'msg': 'Transform estimation failed.'}), 500

    # Step 2: Compute precise tag positions via the rigid transform
    import numpy as np
    from uwb_web.services.calibration import apply_rigid_transform
    precise_tags = apply_rigid_transform(
        motion_mm, transform['R'], transform['t'], transform['scale']
    )
    tag_positions = [(float(r[0]), float(r[1])) for r in precise_tags]

    # Step 3: Get current anchor positions
    initial_anchors = {}
    for d in Device.query.filter_by(is_anchor=True).all():
        if d.x is not None and d.y is not None:
            initial_anchors[d.id] = (d.x, d.y)

    if not initial_anchors:
        return jsonify({'status': 'error', 'msg': 'No anchors with positions.'}), 400

    # Step 4: Refine
    result = refine_anchor_positions(
        tag_positions, range_data_list, initial_anchors,
    )
    if result is None:
        return jsonify({'status': 'error',
                        'msg': 'Not enough data to refine anchors.'}), 400

    return jsonify({'status': 'ok', 'transform': transform, **result})


@bp.route('/api/apply-refined-anchors', methods=['POST'])
def api_apply_refined_anchors():
    """
    Apply refined anchor positions to the database.

    Body: { "anchors": {device_id: {"x": float, "y": float}} }
    """
    from uwb_web.models import Device
    from uwb_web.db import db

    data = request.get_json(silent=True) or {}
    anchors = data.get('anchors', {})
    if not anchors:
        return jsonify({'status': 'error', 'msg': 'No anchors provided.'}), 400

    updated = 0
    for did_str, coords in anchors.items():
        did = int(did_str)
        device = db.session.get(Device, did)
        if device and device.is_anchor:
            device.x = coords['x']
            device.y = coords['y']
            updated += 1

    db.session.commit()
    logger.info('Applied refined positions for %d anchors', updated)

    # Reload engine so new anchor positions are used
    from uwb_web import get_serial_worker
    worker = get_serial_worker()
    if worker:
        worker.reload_engine()

    return jsonify({'status': 'ok', 'updated': updated})


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
