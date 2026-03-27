"""
Calibration service — move the UWB tag to known positions using the
motion controller, collect range data, compute per-anchor corrections,
and apply them to improve real-time positioning.

Corrections model (per anchor):
    corrected_range = (measured_range - bias) / scale

The bias and scale are computed via linear regression on
    measured_range  vs  true_range  (Euclidean distance from true
    tag position to anchor position).
"""

import json
import math
import time
import threading
import logging
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Analysis helpers (pure functions — no DB / Flask deps)
# ──────────────────────────────────────────────────────────────────────

def _euclidean(a, b):
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def compute_corrections(points_data, anchors):
    """
    Compute per-anchor range corrections from calibration data.

    Args:
        points_data: list of dicts, each with:
            true_x, true_y, true_z, ranges_json (parsed dict)
        anchors: dict  {device_id: {'hex': str, 'x': float, 'y': float, 'z': float|None}}

    Returns:
        dict keyed by device_id:
            { 'hex': str, 'bias': float, 'scale': float,
              'mean_error': float, 'std_error': float, 'n_samples': int }
    """
    # Accumulate (true_range, measured_range) pairs per anchor
    per_anchor = {}  # device_id -> [(true_range, measured_range), ...]

    for pt in points_data:
        true_pos = (pt['true_x'], pt['true_y'], pt['true_z'])
        ranges = pt.get('ranges') or {}
        for hex_addr, info in ranges.items():
            did = info.get('device_id')
            if did is None or did not in anchors:
                continue
            a = anchors[did]
            anchor_pos = (a['x'], a['y'], a.get('z') or 0.0)
            true_range = _euclidean(true_pos, anchor_pos)
            measured_range = info['mean']
            if true_range > 0 and measured_range > 0:
                per_anchor.setdefault(did, []).append((true_range, measured_range))

    corrections = {}
    for did, pairs in per_anchor.items():
        if len(pairs) < 2:
            continue
        true_arr = np.array([p[0] for p in pairs])
        meas_arr = np.array([p[1] for p in pairs])

        # Linear fit: measured = scale * true + bias
        A = np.vstack([true_arr, np.ones(len(true_arr))]).T
        result, _, _, _ = np.linalg.lstsq(A, meas_arr, rcond=None)
        scale, bias = float(result[0]), float(result[1])

        # Prevent degenerate scale
        if abs(scale) < 0.01:
            scale = 1.0

        # Corrected ranges and residual stats
        corrected = (meas_arr - bias) / scale
        errors = corrected - true_arr
        corrections[did] = {
            'hex': anchors[did]['hex'],
            'bias': round(bias, 6),
            'scale': round(scale, 6),
            'mean_error': round(float(np.mean(np.abs(errors))), 6),
            'std_error': round(float(np.std(errors)), 6),
            'n_samples': len(pairs),
        }
    return corrections


def compute_position_stats(points_data):
    """
    Compute position error statistics from calibration points.

    Returns dict with rmse, mean_error, max_error, n_points.
    """
    errors = []
    for pt in points_data:
        if pt.get('uwb_x') is None:
            continue
        true = (pt['true_x'], pt['true_y'], pt['true_z'])
        est = (pt['uwb_x'], pt['uwb_y'], pt.get('uwb_z') or pt['true_z'])
        errors.append(_euclidean(true, est))

    if not errors:
        return {'rmse': None, 'mean_error': None, 'max_error': None, 'n_points': 0}

    arr = np.array(errors)
    return {
        'rmse': round(float(np.sqrt(np.mean(arr ** 2))), 4),
        'mean_error': round(float(np.mean(arr)), 4),
        'max_error': round(float(np.max(arr)), 4),
        'median_error': round(float(np.median(arr)), 4),
        'n_points': len(errors),
    }


# ──────────────────────────────────────────────────────────────────────
# Coordinate-frame alignment (auto-origin)
# ──────────────────────────────────────────────────────────────────────

def estimate_rigid_transform(motion_pts_mm, uwb_pts_m):
    """
    Estimate the 2-D rigid transform (rotation + translation) that maps
    motion-controller coordinates to UWB room coordinates.

    Uses the SVD-based Procrustes method, which is the optimal least-
    squares fit.  Because the motion controller's *relative* movements
    are very precise, the residual after alignment tells you how much
    the UWB positions scatter — not how bad your tape-measure was.

    Args:
        motion_pts_mm: Nx2 array-like — grid positions in motion-controller
                       space (mm).  Only the relative layout matters.
        uwb_pts_m:     Nx2 array-like — corresponding UWB-estimated
                       positions (metres).

    Returns dict:
        rotation_deg:  rotation angle (°) from motion frame → UWB frame
        translation_m: (tx, ty) — UWB position of the motion origin
        scale:         scale factor (should be ≈ 0.001 since mm → m)
        rmse_m:        residual RMSE after alignment (metres)
        R:             2×2 rotation matrix (list of lists)
        t:             translation vector [tx, ty]
    """
    M = np.asarray(motion_pts_mm, dtype=float)
    U = np.asarray(uwb_pts_m, dtype=float)
    if M.shape[0] < 3 or M.shape != U.shape:
        return None

    # Centroids
    cm = M.mean(axis=0)
    cu = U.mean(axis=0)

    # Centre the point sets
    Mc = M - cm
    Uc = U - cu

    # Solve for R and s using SVD of the cross-covariance matrix
    H = Mc.T @ Uc                # 2×2
    Usvd, S, Vt = np.linalg.svd(H)

    # Ensure a proper rotation (det = +1)
    d = np.linalg.det(Vt.T @ Usvd.T)
    D = np.diag([1.0, np.sign(d)])
    R = Vt.T @ D @ Usvd.T

    # Scale: ratio of UWB spread to motion spread
    scale = float(np.sum(S) / np.sum(Mc ** 2))

    # Translation
    t = cu - scale * R @ cm

    # Residual
    aligned = (scale * (R @ M.T)).T + t
    residuals = np.sqrt(np.sum((aligned - U) ** 2, axis=1))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))

    angle = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))

    return {
        'rotation_deg': round(angle, 3),
        'translation_m': [round(float(t[0]), 6), round(float(t[1]), 6)],
        'scale': round(scale, 8),
        'rmse_m': round(rmse, 6),
        'R': [[round(float(R[i, j]), 8) for j in range(2)] for i in range(2)],
        't': [round(float(t[0]), 6), round(float(t[1]), 6)],
        'per_point_error_m': [round(float(e), 6) for e in residuals],
    }


def apply_rigid_transform(motion_pts_mm, R, t, scale):
    """
    Map motion-controller mm points to UWB metres using a rigid transform.

    Args:
        motion_pts_mm: Nx2 array   (mm, motion-controller frame)
        R:             2×2 rotation matrix
        t:             [tx, ty] translation (metres)
        scale:         scale factor

    Returns:
        Nx2 array of positions in UWB metres.
    """
    M = np.asarray(motion_pts_mm, dtype=float)
    R = np.asarray(R, dtype=float)
    t = np.asarray(t, dtype=float)
    return (scale * (R @ M.T)).T + t


# ──────────────────────────────────────────────────────────────────────
# Anchor position refinement
# ──────────────────────────────────────────────────────────────────────

def refine_anchor_positions(tag_positions_m, range_data, initial_anchors,
                            max_iterations=50, tol=1e-6):
    """
    Optimise anchor positions using precise tag positions and measured
    ranges via Gauss-Newton.

    The motion controller gives very precise *relative* tag positions.
    After applying the rigid transform they become precise *absolute*
    positions.  We can then ask: "given these tag positions, what anchor
    positions best explain all the range measurements?"

    This is a standard nonlinear least-squares problem:
        min_a  Σᵢ Σⱼ wⱼ (rᵢⱼ - ||tagᵢ - anchorⱼ||)²

    where rᵢⱼ is the measured range from tag position i to anchor j.

    Args:
        tag_positions_m: list of (x, y) — precise tag positions (metres)
        range_data:      list of dicts, one per tag position.
                         Each: {device_id: {'mean': float, 'weight': float}}
        initial_anchors: {device_id: (x, y)} — current anchor positions
        max_iterations:  Gauss-Newton iteration cap
        tol:             convergence threshold (change in parameter norm)

    Returns dict:
        anchors:  {device_id: {'x': float, 'y': float,
                               'dx': delta_x, 'dy': delta_y}}
        rmse_before: float
        rmse_after: float
        iterations: int
    """
    anchor_ids = sorted(initial_anchors.keys())
    if len(anchor_ids) < 1 or len(tag_positions_m) < 2:
        return None

    # Parameter vector: [ax0, ay0, ax1, ay1, ...]
    params = np.array(
        [c for aid in anchor_ids for c in initial_anchors[aid]], dtype=float
    )
    n_anchors = len(anchor_ids)
    aid_to_idx = {aid: i for i, aid in enumerate(anchor_ids)}

    # Build observation list: (tag_idx, anchor_param_idx, measured_range, weight)
    observations = []
    for ti, (rd) in enumerate(range_data):
        for did, info in rd.items():
            did = int(did)
            if did not in aid_to_idx:
                continue
            r = info.get('mean')
            w = info.get('weight', 1.0)
            if r is not None and r > 0:
                observations.append((ti, aid_to_idx[did], r, w))

    if len(observations) < 2 * n_anchors:
        return None          # not enough data to constrain all anchors

    tags = np.array(tag_positions_m, dtype=float)   # N×2
    params_init = params.copy()

    def _compute_residuals(p):
        res = np.empty(len(observations))
        for k, (ti, ai, meas, _) in enumerate(observations):
            ax, ay = p[2*ai], p[2*ai+1]
            dx, dy = tags[ti, 0] - ax, tags[ti, 1] - ay
            pred = math.sqrt(dx*dx + dy*dy)
            res[k] = meas - pred
        return res

    def _rmse(p):
        r = _compute_residuals(p)
        return float(np.sqrt(np.mean(r**2)))

    rmse_before = _rmse(params)

    # Gauss-Newton iterations
    iterations = 0
    for it in range(max_iterations):
        iterations = it + 1
        res = np.empty(len(observations))
        J = np.zeros((len(observations), 2 * n_anchors))

        for k, (ti, ai, meas, w) in enumerate(observations):
            ax, ay = params[2*ai], params[2*ai+1]
            dx, dy = tags[ti, 0] - ax, tags[ti, 1] - ay
            dist = math.sqrt(dx*dx + dy*dy)
            if dist < 1e-9:
                dist = 1e-9
            res[k] = w * (meas - dist)
            # Jacobian of -dist w.r.t. anchor params [ax, ay]
            J[k, 2*ai]   = w * (dx / dist)     # ∂(-dist)/∂ax = dx/dist
            J[k, 2*ai+1] = w * (dy / dist)

        # Normal equations: (J^T J) Δp = J^T r
        JtJ = J.T @ J
        # Damping for robustness (Levenberg)
        JtJ += 1e-6 * np.eye(JtJ.shape[0])
        Jtr = J.T @ res

        try:
            dp = np.linalg.solve(JtJ, Jtr)
        except np.linalg.LinAlgError:
            break

        params -= dp

        if np.linalg.norm(dp) < tol:
            break

    rmse_after = _rmse(params)

    result_anchors = {}
    for i, aid in enumerate(anchor_ids):
        ox, oy = initial_anchors[aid]
        nx, ny = float(params[2*i]), float(params[2*i+1])
        result_anchors[aid] = {
            'x': round(nx, 4), 'y': round(ny, 4),
            'dx': round(nx - ox, 4), 'dy': round(ny - oy, 4),
        }

    return {
        'anchors': result_anchors,
        'rmse_before': round(rmse_before, 6),
        'rmse_after': round(rmse_after, 6),
        'iterations': iterations,
    }


def apply_range_correction(measured, bias, scale):
    """Apply an affine correction to a single range measurement."""
    if abs(scale) < 0.01:
        return measured
    return (measured - bias) / scale


# ──────────────────────────────────────────────────────────────────────
# Active corrections — loaded from DB, applied at trilateration time
# ──────────────────────────────────────────────────────────────────────

_corrections_cache = None
_corrections_lock = threading.Lock()


def get_active_corrections(app):
    """
    Return dict {device_id: {'bias': float, 'scale': float}} or empty dict.

    Cached; call invalidate_corrections_cache() after updates.
    """
    global _corrections_cache
    with _corrections_lock:
        if _corrections_cache is not None:
            return _corrections_cache

    with app.app_context():
        from uwb_web.services.config_service import get_config
        raw = get_config('cal_corrections')
        enabled = get_config('cal_corrections_enabled', 'false')
        if enabled != 'true' or not raw:
            with _corrections_lock:
                _corrections_cache = {}
            return {}
        try:
            data = json.loads(raw)
            # dict keyed by str(device_id) -> {bias, scale}
            result = {int(k): v for k, v in data.items()}
        except Exception:
            result = {}
        with _corrections_lock:
            _corrections_cache = result
        return result


def invalidate_corrections_cache():
    global _corrections_cache
    with _corrections_lock:
        _corrections_cache = None


def correct_ranges(ranges, corrections):
    """
    Apply per-anchor affine corrections to a ranges dict.

    Args:
        ranges: dict {device_id: range_m}
        corrections: dict {device_id: {'bias': float, 'scale': float}}

    Returns:
        new dict with corrected ranges.
    """
    if not corrections:
        return ranges
    out = {}
    for did, r in ranges.items():
        if r is None:
            out[did] = r
            continue
        c = corrections.get(did)
        if c:
            out[did] = apply_range_correction(r, c['bias'], c['scale'])
        else:
            out[did] = r
    return out


# ──────────────────────────────────────────────────────────────────────
# Calibration runner (background thread)
# ──────────────────────────────────────────────────────────────────────

class CalibrationRunner:
    """
    Orchestrates a calibration run:
      1. Generate grid points
      2. Move to each point via motion controller
      3. Dwell and collect UWB measurements
      4. Analyse and compute corrections
    """

    def __init__(self, app):
        self.app = app
        self.status = 'idle'       # idle | running | completed | failed | cancelled
        self.progress = {}         # {current: int, total: int, phase: str}
        self.run_id = None
        self._thread = None
        self._cancel = threading.Event()

    @property
    def is_busy(self):
        return self.status == 'running'

    def start(self, *, grid_points, origin, dwell, speed, name=None):
        """
        Start a calibration run in a background thread.

        Args:
            grid_points: list of {'x': mm, 'y': mm, 'z': mm}
            origin: {'x': m, 'y': m, 'z': m}  UWB coords of motion origin
            dwell: seconds to collect at each point
            speed: motion speed in mm/s
            name: optional run name
        """
        if self.is_busy:
            return False, 'Calibration already running.'
        self._cancel.clear()
        self.status = 'running'
        self.progress = {'current': 0, 'total': len(grid_points), 'phase': 'starting'}
        self._thread = threading.Thread(
            target=self._run,
            args=(grid_points, origin, dwell, speed, name),
            daemon=True,
        )
        self._thread.start()
        return True, 'Calibration started.'

    def cancel(self):
        if self.is_busy:
            self._cancel.set()
            return True
        return False

    # ── internal ──────────────────────────────────────────────────────

    def _run(self, grid_points, origin, dwell, speed, name):
        from uwb_web.db import db
        from uwb_web.models import CalibrationRun, CalibrationPoint
        from uwb_web.routes.motion import _get_client as get_motion_client

        run = None
        try:
            with self.app.app_context():
                run = CalibrationRun(
                    name=name or f'Cal {datetime.now(timezone.utc):%Y-%m-%d %H:%M}',
                    origin_x=origin['x'], origin_y=origin['y'], origin_z=origin['z'],
                    dwell_seconds=dwell, speed_mm_s=speed,
                    grid_config_json=json.dumps(grid_points),
                )
                db.session.add(run)
                db.session.commit()
                self.run_id = run.id

                for idx, pt in enumerate(grid_points):
                    if self._cancel.is_set():
                        run.status = 'cancelled'
                        db.session.commit()
                        self.status = 'cancelled'
                        self.progress['phase'] = 'cancelled'
                        return

                    self.progress = {
                        'current': idx + 1,
                        'total': len(grid_points),
                        'phase': 'moving',
                    }

                    # Move to position (non-blocking, then poll)
                    try:
                        get_motion_client().move_absolute(
                            pt['x'], pt['y'], pt['z'], speed=speed, wait=False,
                        )
                    except Exception as e:
                        logger.error('Motion move failed: %s', e)
                        run.status = 'failed'
                        db.session.commit()
                        self.status = 'failed'
                        self.progress['phase'] = f'move error: {e}'
                        return

                    # Wait for movement to finish
                    if not self._wait_motion_ready(get_motion_client):
                        if self._cancel.is_set():
                            run.status = 'cancelled'
                            db.session.commit()
                            self.status = 'cancelled'
                            return
                        run.status = 'failed'
                        db.session.commit()
                        self.status = 'failed'
                        self.progress['phase'] = 'motion timeout'
                        return

                    # Dwell and collect
                    self.progress['phase'] = 'collecting'
                    samples = self._collect_samples(dwell)

                    # True position in UWB metres
                    true_x = pt['x'] / 1000.0 + origin['x']
                    true_y = pt['y'] / 1000.0 + origin['y']
                    true_z = pt['z'] / 1000.0 + origin['z']

                    # Aggregate ranges per anchor
                    agg_ranges = self._aggregate_ranges(samples)

                    # Averaged UWB position from samples
                    uwb_x, uwb_y, uwb_z = self._average_position(samples)

                    error = None
                    if uwb_x is not None:
                        z_err = (uwb_z or true_z) - true_z
                        error = math.sqrt(
                            (uwb_x - true_x) ** 2 +
                            (uwb_y - true_y) ** 2 +
                            z_err ** 2
                        )

                    cp = CalibrationPoint(
                        run_id=run.id, point_index=idx,
                        true_x=true_x, true_y=true_y, true_z=true_z,
                        uwb_x=uwb_x, uwb_y=uwb_y, uwb_z=uwb_z,
                        ranges_json=json.dumps(agg_ranges),
                        error_m=round(error, 6) if error is not None else None,
                        collected_at_utc=datetime.now(timezone.utc),
                    )
                    db.session.add(cp)
                    db.session.commit()

                # Analyse
                self.progress['phase'] = 'analysing'
                self._analyse_run(run)
                run.status = 'completed'
                run.finished_at_utc = datetime.now(timezone.utc)
                db.session.commit()
                self.status = 'completed'
                self.progress['phase'] = 'done'

        except Exception:
            logger.exception('Calibration run failed')
            self.status = 'failed'
            self.progress['phase'] = 'internal error'
            if run:
                try:
                    with self.app.app_context():
                        run.status = 'failed'
                        db.session.commit()
                except Exception:
                    pass

    def _wait_motion_ready(self, get_client, timeout=120):
        """Poll motion controller status until idle, with timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                return False
            try:
                resp = get_client().get_status()
                state = resp.get('state', {})
                is_busy = state.get('is_busy', True)
                if not is_busy:
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def _collect_samples(self, dwell_seconds):
        """Collect UWB data for the given dwell period."""
        from uwb_web import get_serial_worker
        samples = []
        end = time.monotonic() + dwell_seconds
        while time.monotonic() < end:
            if self._cancel.is_set():
                break
            worker = get_serial_worker()
            if worker:
                pos_data = worker.get_position()
                live = worker.get_live_data()
                samples.append({
                    'position': pos_data.get('position'),
                    'live': live,
                    'ts': time.monotonic(),
                })
            time.sleep(0.1)
        return samples

    def _aggregate_ranges(self, samples):
        """Aggregate per-anchor range measurements from collected samples."""
        from uwb_web.models import Device
        # Collect raw ranges per hex address
        per_anchor = {}  # hex -> list of range values
        for s in samples:
            for hex_addr, info in (s.get('live') or {}).items():
                r = info.get('range_m')
                if r is not None and r > 0:
                    per_anchor.setdefault(hex_addr, []).append(r)

        # Look up device IDs and compute stats
        result = {}
        for hex_addr, values in per_anchor.items():
            device = Device.query.filter_by(short_addr_hex=hex_addr, is_anchor=True).first()
            if not device:
                continue
            arr = np.array(values)
            result[hex_addr] = {
                'device_id': device.id,
                'mean': round(float(np.mean(arr)), 6),
                'std': round(float(np.std(arr)), 6),
                'count': len(values),
            }
        return result

    def _average_position(self, samples):
        """Average UWB position estimates from samples."""
        xs, ys, zs = [], [], []
        for s in samples:
            p = s.get('position')
            if p and p.get('x') is not None:
                xs.append(p['x'])
                ys.append(p['y'])
                if 'z' in p and p['z'] is not None:
                    zs.append(p['z'])
        if not xs:
            return None, None, None
        z = round(float(np.mean(zs)), 6) if zs else None
        return round(float(np.mean(xs)), 6), round(float(np.mean(ys)), 6), z

    def _analyse_run(self, run):
        """Compute corrections and stats for a completed run, store in run.results_json."""
        from uwb_web.models import Device
        points = run.points.all()

        points_data = []
        for p in points:
            rd = json.loads(p.ranges_json) if p.ranges_json else {}
            points_data.append({
                'true_x': p.true_x, 'true_y': p.true_y, 'true_z': p.true_z,
                'uwb_x': p.uwb_x, 'uwb_y': p.uwb_y, 'uwb_z': p.uwb_z,
                'ranges': rd,
            })

        # Build anchors dict
        anchors = {}
        for d in Device.query.filter_by(is_anchor=True).all():
            if d.x is not None and d.y is not None:
                anchors[d.id] = {'hex': d.short_addr_hex, 'x': d.x, 'y': d.y, 'z': d.z}

        corrections = compute_corrections(points_data, anchors)
        stats_before = compute_position_stats(points_data)

        # Simulate "after" corrections: re-trilaterate with corrected ranges
        stats_after = self._simulate_corrected_stats(points_data, anchors, corrections)

        results = {
            'corrections': {str(k): v for k, v in corrections.items()},
            'stats_before': stats_before,
            'stats_after': stats_after,
        }
        run.results_json = json.dumps(results)

    def _simulate_corrected_stats(self, points_data, anchors, corrections):
        """Re-run trilateration with corrected ranges and compute position stats."""
        from uwb_web.services.trilateration import estimate_position_2d

        corrected_pts = []
        anchors_2d = {did: (a['x'], a['y']) for did, a in anchors.items()}

        for pt in points_data:
            raw_ranges = pt.get('ranges') or {}
            corrected_ranges = {}
            for hex_addr, info in raw_ranges.items():
                did = info.get('device_id')
                if did is None:
                    continue
                r = info['mean']
                c = corrections.get(did)
                if c:
                    r = apply_range_correction(r, c['bias'], c['scale'])
                corrected_ranges[did] = r

            pos = estimate_position_2d(corrected_ranges, anchors_2d)
            corrected_pts.append({
                'true_x': pt['true_x'],
                'true_y': pt['true_y'],
                'true_z': pt['true_z'],
                'uwb_x': pos[0] if pos else None,
                'uwb_y': pos[1] if pos else None,
                'uwb_z': None,
            })

        return compute_position_stats(corrected_pts)
