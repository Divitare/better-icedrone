"""
Advanced position estimation engine.

Combines multiple techniques — like deconvolving a blurred photograph —
to extract the sharpest possible position from noisy UWB range data:

1. **Weighted Least Squares (WLS)** trilateration: weight each anchor by
   the inverse of its measured variance (from calibration).  Anchors that
   consistently return precise ranges get more say.

2. **Residual-based NLOS rejection**: after an initial solve, compute
   per-anchor residuals. Iteratively drop the worst outlier (likely a
   reflected / non-line-of-sight path) and re-solve until residuals are
   acceptable.  This is analogous to masking artifacts in an image before
   deconvolution.

3. **Extended Kalman Filter (EKF)**: maintain a state [x, y, vx, vy] and
   fuse each incoming range measurement sequentially.  The constant-
   velocity motion model encodes the physical constraint that the tag
   can't teleport — exactly the "temporal coherence" that makes image
   deblurring work when the camera moves.

4. **RTS trajectory smoother** (batch "deblurring"): given a recorded
   sequence of positions, run a forward Kalman pass then a backward
   Rauch–Tung–Striebel pass to produce an optimally smoothed trajectory.
   Every position is refined using *both* past and future data — the
   exact analogue of Wiener deconvolution for a 1-D signal.
"""

import math
import time
import threading
import logging

import numpy as np

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Real-time position engine
# ──────────────────────────────────────────────────────────────────────

class PositionEngine:
    """Stateful position estimator: WLS → NLOS rejection → EKF."""

    def __init__(self):
        self._ekf = None
        self._anchor_weights = {}   # device_id → {'variance': float, 'weight': float}
        self._anchor_z = {}         # device_id → z (metres)
        self._last_update_t = None
        self._lock = threading.Lock()

        # Tuneable parameters (overridden by DB config)
        self.ekf_enabled = True
        self.nlos_rejection_enabled = True
        self.nlos_residual_threshold = 0.5    # metres
        self.ekf_process_noise = 0.1          # m/s² acceleration uncertainty
        self.ekf_initial_pos_var = 1.0        # m²
        self.ekf_initial_vel_var = 0.5        # (m/s)²
        self.default_range_var = 0.1          # m² — used when no calibration data
        self.tag_z = 0.0                      # tag height (metres)

    # -- configuration --------------------------------------------------

    def set_anchor_weights(self, weights):
        """weights: {device_id: {'variance': float, 'weight': float}}"""
        with self._lock:
            self._anchor_weights = dict(weights)

    def set_anchor_heights(self, anchor_z):
        """anchor_z: {device_id: z_metres}"""
        with self._lock:
            self._anchor_z = dict(anchor_z)

    def load_settings(self, cfg):
        """Load settings dict (from DB / API)."""
        if 'ekf_enabled' in cfg:
            self.ekf_enabled = cfg['ekf_enabled']
        if 'nlos_enabled' in cfg:
            self.nlos_rejection_enabled = cfg['nlos_enabled']
        if 'nlos_threshold' in cfg:
            self.nlos_residual_threshold = float(cfg['nlos_threshold'])
        if 'process_noise' in cfg:
            self.ekf_process_noise = float(cfg['process_noise'])
        if 'range_var' in cfg:
            self.default_range_var = float(cfg['range_var'])
        if 'tag_z' in cfg:
            self.tag_z = float(cfg['tag_z'])

    def reset(self):
        """Discard EKF state (call after tag repositioning / settings change)."""
        with self._lock:
            self._ekf = None
            self._last_update_t = None

    # -- main entry point -----------------------------------------------

    def update(self, ranges, anchors_2d, dt=None):
        """
        Process the current set of ranges and return an enriched position.

        Args:
            ranges:      {device_id: range_m}
            anchors_2d:  {device_id: (x, y)}
            dt:          seconds since last call (auto-computed if None)

        Returns dict with keys x, y, vx, vy, confidence, used_anchors,
        rejected_anchors, method  — or None.
        """
        with self._lock:
            return self._process(ranges, anchors_2d, dt)

    # -- internal pipeline stages ---------------------------------------

    def _process(self, ranges, anchors_2d, dt):
        available = {did: r for did, r in ranges.items()
                     if did in anchors_2d and r is not None and r > 0}
        if len(available) < 3:
            return None

        # Project 3-D slant ranges to 2-D horizontal ranges
        available = _project_ranges_2d(available, self._anchor_z, self.tag_z)

        weights = {}
        for did in available:
            w = self._anchor_weights.get(did, {})
            weights[did] = w.get('weight', 1.0)

        # Stage 1 — Weighted trilateration
        pos_wls = _wls_trilaterate(available, anchors_2d, weights)
        if pos_wls is None:
            return None

        used = list(available.keys())
        rejected = []

        # Stage 2 — NLOS rejection (need ≥ 4 anchors to afford dropping one)
        if self.nlos_rejection_enabled and len(available) >= 4:
            pos_clean, used, rejected = _nlos_rejection(
                available, anchors_2d, weights,
                pos_wls, self.nlos_residual_threshold,
            )
            if pos_clean is not None:
                pos_wls = pos_clean

        # Stage 3 — EKF
        if self.ekf_enabled:
            now = time.monotonic()
            if dt is None:
                dt = (now - self._last_update_t) if self._last_update_t else 0.1
            self._last_update_t = now

            if self._ekf is None:
                self._ekf = _EKF2D(
                    pos_wls[0], pos_wls[1],
                    pos_var=self.ekf_initial_pos_var,
                    vel_var=self.ekf_initial_vel_var,
                )

            self._ekf.predict(dt, self.ekf_process_noise)

            meas_var = {}
            for did in used:
                w = self._anchor_weights.get(did, {})
                meas_var[did] = w.get('variance', self.default_range_var)

            self._ekf.update_ranges(
                {did: available[did] for did in used},
                {did: anchors_2d[did] for did in used},
                meas_var,
            )

            state = self._ekf.state
            cov = self._ekf.P
            x, y = float(state[0]), float(state[1])
            vx, vy = float(state[2]), float(state[3])

            pos_unc = math.sqrt(max(0, cov[0, 0]) + max(0, cov[1, 1]))
            confidence = max(0.0, min(1.0, 1.0 - pos_unc / 2.0))

            return {
                'x': round(x, 4), 'y': round(y, 4),
                'vx': round(vx, 4), 'vy': round(vy, 4),
                'confidence': round(confidence, 3),
                'covariance': [
                    [round(float(cov[0, 0]), 6), round(float(cov[0, 1]), 6)],
                    [round(float(cov[1, 0]), 6), round(float(cov[1, 1]), 6)],
                ],
                'used_anchors': used,
                'rejected_anchors': rejected,
                'method': 'ekf',
            }

        # Fallback — WLS / plain LS only
        return {
            'x': round(pos_wls[0], 4), 'y': round(pos_wls[1], 4),
            'vx': 0.0, 'vy': 0.0,
            'confidence': 0.5,
            'covariance': None,
            'used_anchors': used,
            'rejected_anchors': rejected,
            'method': 'wls' if any(w != 1.0 for w in weights.values()) else 'ls',
        }


# ──────────────────────────────────────────────────────────────────────
# Weighted least-squares trilateration
# ──────────────────────────────────────────────────────────────────────

def _project_ranges_2d(ranges, anchor_z, tag_z):
    """
    Convert 3-D slant ranges to 2-D horizontal ranges.

    UWB measures line-of-sight (3-D) distance.  When doing 2-D
    trilateration the vertical component must be removed:
        r_horiz = sqrt(r_slant² - Δz²)
    """
    if not anchor_z:
        return ranges
    projected = {}
    for did, r in ranges.items():
        az = anchor_z.get(did)
        if az is not None:
            dz = az - tag_z
            r_sq = r * r - dz * dz
            projected[did] = math.sqrt(r_sq) if r_sq > 0 else r
        else:
            projected[did] = r
    return projected


def _wls_trilaterate(ranges, anchors, weights):
    """
    2D weighted least-squares trilateration (reference-subtraction).

    Returns (x, y) or None.
    """
    available = list(ranges.keys())
    if len(available) < 3:
        return None

    try:
        ref = available[0]
        x0, y0 = anchors[ref]
        r0 = ranges[ref]

        A_rows, b_rows, w_vals = [], [], []
        for did in available[1:]:
            xi, yi = anchors[did]
            ri = ranges[did]
            A_rows.append([2.0 * (xi - x0), 2.0 * (yi - y0)])
            b_rows.append(r0**2 - ri**2 + xi**2 - x0**2 + yi**2 - y0**2)
            w_vals.append(math.sqrt(weights.get(ref, 1.0) * weights.get(did, 1.0)))

        A = np.array(A_rows, dtype=float)
        b = np.array(b_rows, dtype=float)
        W = np.diag(w_vals)

        AtW = A.T @ W
        result = np.linalg.solve(AtW @ A, AtW @ b)
        x, y = float(result[0]), float(result[1])

        # Sanity: reject wild extrapolations
        cx = np.mean([anchors[d][0] for d in available])
        cy = np.mean([anchors[d][1] for d in available])
        max_r = max(ranges[d] for d in available)
        if abs(x - cx) > max_r * 3 or abs(y - cy) > max_r * 3:
            return None

        return (x, y)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────
# NLOS rejection
# ──────────────────────────────────────────────────────────────────────

def _nlos_rejection(ranges, anchors, weights, initial_pos, threshold):
    """
    Iteratively drop the anchor with the largest residual until all
    residuals < threshold or we'd drop below 3 anchors.

    Returns (pos, used_ids, rejected_ids).
    """
    current = dict(ranges)
    cur_w = dict(weights)
    rejected = []
    pos = initial_pos

    while len(current) >= 4:
        residuals = {}
        for did, r in current.items():
            ax, ay = anchors[did]
            expected = math.sqrt((pos[0] - ax) ** 2 + (pos[1] - ay) ** 2)
            residuals[did] = abs(r - expected)

        worst = max(residuals, key=residuals.get)
        if residuals[worst] < threshold:
            break

        saved_r = current.pop(worst)
        saved_w = cur_w.pop(worst, 1.0)
        rejected.append(worst)

        new_pos = _wls_trilaterate(current, anchors, cur_w)
        if new_pos is None:
            current[worst] = saved_r
            cur_w[worst] = saved_w
            rejected.pop()
            break
        pos = new_pos

    return pos, list(current.keys()), rejected


# ──────────────────────────────────────────────────────────────────────
# Extended Kalman Filter (EKF) for 2D position tracking
# ──────────────────────────────────────────────────────────────────────

class _EKF2D:
    """
    State [x, y, vx, vy].
    Motion model: constant velocity with Gaussian acceleration noise.
    Measurement model: range_i = ||pos - anchor_i||.
    """

    def __init__(self, x0, y0, pos_var=1.0, vel_var=0.5):
        self.state = np.array([x0, y0, 0.0, 0.0], dtype=float)
        self.P = np.diag([pos_var, pos_var, vel_var, vel_var])

    def predict(self, dt, q_accel):
        """Constant-velocity prediction with process noise q_accel (m/s²)."""
        F = np.eye(4)
        F[0, 2] = dt
        F[1, 3] = dt

        dt2 = dt * dt
        dt3 = dt2 * dt / 2.0
        dt4 = dt2 * dt2 / 4.0
        Q = q_accel * np.array([
            [dt4, 0,   dt3, 0  ],
            [0,   dt4, 0,   dt3],
            [dt3, 0,   dt2, 0  ],
            [0,   dt3, 0,   dt2],
        ])

        self.state = F @ self.state
        self.P = F @ self.P @ F.T + Q

    def update_ranges(self, ranges, anchors, measurement_variances):
        """
        Sequential EKF update — one range observation at a time.

        For each anchor the measurement model is:
            h(x) = sqrt((x − a_x)² + (y − a_y)²)
        Jacobian:
            H = [(x−a_x)/h,  (y−a_y)/h,  0,  0]
        """
        x, y = self.state[0], self.state[1]

        for did, measured in ranges.items():
            if did not in anchors:
                continue
            ax, ay = anchors[did]
            dx, dy = x - ax, y - ay
            predicted = math.sqrt(dx * dx + dy * dy)
            if predicted < 1e-6:
                continue

            H = np.array([[dx / predicted, dy / predicted, 0.0, 0.0]])
            innovation = measured - predicted
            R = np.array([[measurement_variances.get(did, 0.1)]])

            S = H @ self.P @ H.T + R
            K = self.P @ H.T @ np.linalg.inv(S)

            self.state = self.state + (K @ np.array([innovation])).flatten()
            self.P = (np.eye(4) - K @ H) @ self.P

            x, y = self.state[0], self.state[1]


# ──────────────────────────────────────────────────────────────────────
# Trajectory smoother — the "deblurring" algorithm
# ──────────────────────────────────────────────────────────────────────

def smooth_trajectory(positions, dt=0.1, process_noise=0.1,
                      measurement_noise=0.01):
    """
    Rauch–Tung–Striebel (RTS) backward smoother.

    Analogous to Wiener deconvolution of a 1-D signal: each position is
    "sharpened" using information from its *entire* temporal neighbourhood,
    not just the past.

    Args:
        positions:         list of {'x': float, 'y': float, ...}
        dt:                seconds between samples
        process_noise:     acceleration uncertainty (m/s²)
        measurement_noise: position measurement variance (m²)

    Returns:
        list of {'x', 'y', 'vx', 'vy', 'confidence', 'ts'?}
    """
    if len(positions) < 3:
        return list(positions)

    n = len(positions)

    # State transition [x, y, vx, vy]
    F = np.eye(4)
    F[0, 2] = dt
    F[1, 3] = dt

    q = process_noise
    dt2, dt3, dt4 = dt * dt, dt ** 3 / 2.0, dt ** 4 / 4.0
    Q = q * np.array([
        [dt4, 0,   dt3, 0  ],
        [0,   dt4, 0,   dt3],
        [dt3, 0,   dt2, 0  ],
        [0,   dt3, 0,   dt2],
    ])

    H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
    R = measurement_noise * np.eye(2)

    # ---- forward Kalman pass ----
    states_f = []
    covs_f = []

    state = np.array([positions[0]['x'], positions[0]['y'], 0.0, 0.0])
    P = np.diag([measurement_noise, measurement_noise, 1.0, 1.0])

    for i in range(n):
        if i > 0:
            state = F @ state
            P = F @ P @ F.T + Q

        z = np.array([positions[i]['x'], positions[i]['y']])
        innov = z - H @ state
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)
        state = state + K @ innov
        P = (np.eye(4) - K @ H) @ P

        states_f.append(state.copy())
        covs_f.append(P.copy())

    # ---- backward RTS pass ----
    states_s = [None] * n
    covs_s = [None] * n
    states_s[-1] = states_f[-1]
    covs_s[-1] = covs_f[-1]

    for i in range(n - 2, -1, -1):
        P_pred = F @ covs_f[i] @ F.T + Q
        C = covs_f[i] @ F.T @ np.linalg.inv(P_pred)
        states_s[i] = states_f[i] + C @ (states_s[i + 1] - F @ states_f[i])
        covs_s[i] = covs_f[i] + C @ (covs_s[i + 1] - P_pred) @ C.T

    # ---- build output ----
    result = []
    for i in range(n):
        s = states_s[i]
        Ps = covs_s[i]
        unc = math.sqrt(max(0, Ps[0, 0]) + max(0, Ps[1, 1]))
        conf = max(0.0, min(1.0, 1.0 - unc / 2.0))
        entry = {
            'x': round(float(s[0]), 4),
            'y': round(float(s[1]), 4),
            'vx': round(float(s[2]), 4),
            'vy': round(float(s[3]), 4),
            'confidence': round(conf, 3),
        }
        if 'ts' in positions[i]:
            entry['ts'] = positions[i]['ts']
        result.append(entry)

    return result


# ──────────────────────────────────────────────────────────────────────
# Helpers — build anchor weights from calibration corrections
# ──────────────────────────────────────────────────────────────────────

def build_anchor_weights(corrections):
    """
    Convert calibration corrections dict to anchor weights for the engine.

    Args:
        corrections: {device_id: {'std_error': float, ...}} from calibration

    Returns:
        {device_id: {'variance': float, 'weight': float}}
    """
    weights = {}
    for did, c in corrections.items():
        did = int(did)
        std = c.get('std_error', 0.0)
        var = max(std * std, 1e-6)          # clamp away from zero
        weights[did] = {
            'variance': var,
            'weight': 1.0 / var,
        }
    return weights
