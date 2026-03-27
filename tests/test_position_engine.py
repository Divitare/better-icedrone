"""Tests for the advanced position engine (WLS, EKF, NLOS, RTS smoother)."""

import unittest
import math
import json
import random

import numpy as np

from uwb_web.services.position_engine import (
    PositionEngine,
    _wls_trilaterate,
    _nlos_rejection,
    _EKF2D,
    _project_ranges_2d,
    smooth_trajectory,
    build_anchor_weights,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _ranges_from(tag_xy, anchors):
    """Perfect ranges from a 2-D tag position to a dict of anchors."""
    return {
        did: math.sqrt((tag_xy[0] - ax) ** 2 + (tag_xy[1] - ay) ** 2)
        for did, (ax, ay) in anchors.items()
    }


SQUARE_ANCHORS = {1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)}
TAG_POS = (5.0, 5.0)


# ──────────────────────────────────────────────────────────────────────
# WLS trilateration
# ──────────────────────────────────────────────────────────────────────

class TestWLSTrilaterate(unittest.TestCase):

    def test_perfect_3_anchors(self):
        anchors = {1: (0, 0), 2: (6, 0), 3: (3, 5)}
        tag = (2.0, 1.0)
        ranges = _ranges_from(tag, anchors)
        pos = _wls_trilaterate(ranges, anchors, {1: 1, 2: 1, 3: 1})
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 2.0, places=2)
        self.assertAlmostEqual(pos[1], 1.0, places=2)

    def test_perfect_4_anchors(self):
        ranges = _ranges_from(TAG_POS, SQUARE_ANCHORS)
        weights = {d: 1.0 for d in SQUARE_ANCHORS}
        pos = _wls_trilaterate(ranges, SQUARE_ANCHORS, weights)
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 5.0, places=2)
        self.assertAlmostEqual(pos[1], 5.0, places=2)

    def test_weighted_improves_noisy(self):
        """Heavily weighting the accurate anchors should help."""
        anchors = {1: (0, 0), 2: (10, 0), 3: (0, 10), 4: (10, 10)}
        tag = (5.0, 5.0)
        # Anchor 4 has bad measurement; rest are perfect
        ranges = _ranges_from(tag, anchors)
        ranges[4] += 2.0  # bias anchor 4

        # Uniform weights
        pos_u = _wls_trilaterate(ranges, anchors, {d: 1.0 for d in anchors})
        # Down-weight anchor 4
        pos_w = _wls_trilaterate(ranges, anchors, {1: 10, 2: 10, 3: 10, 4: 0.1})

        err_u = math.sqrt((pos_u[0] - 5) ** 2 + (pos_u[1] - 5) ** 2)
        err_w = math.sqrt((pos_w[0] - 5) ** 2 + (pos_w[1] - 5) ** 2)
        self.assertLess(err_w, err_u)

    def test_insufficient_anchors_returns_none(self):
        anchors = {1: (0, 0), 2: (10, 0)}
        ranges = {1: 5.0, 2: 5.0}
        self.assertIsNone(_wls_trilaterate(ranges, anchors, {1: 1, 2: 1}))

    def test_wild_extrapolation_rejected(self):
        """Pathological ranges that would place tag far outside anchors."""
        anchors = {1: (0, 0), 2: (1, 0), 3: (0, 1)}
        # Ranges that are contradictory → solver may produce extreme point
        ranges = {1: 100.0, 2: 0.1, 3: 0.1}
        pos = _wls_trilaterate(ranges, anchors, {1: 1, 2: 1, 3: 1})
        # Either None (sanity failed) or close to anchor cluster
        if pos is not None:
            cx = np.mean([anchors[d][0] for d in anchors])
            cy = np.mean([anchors[d][1] for d in anchors])
            max_r = max(ranges.values())
            self.assertLess(abs(pos[0] - cx), max_r * 3)


# ──────────────────────────────────────────────────────────────────────
# Z-height projection
# ──────────────────────────────────────────────────────────────────────

class TestProjectRanges2D(unittest.TestCase):

    def test_no_heights_returns_same(self):
        """Without anchor z info, ranges pass through unchanged."""
        ranges = {1: 5.0, 2: 3.0}
        result = _project_ranges_2d(ranges, {}, 0.0)
        self.assertEqual(result, ranges)

    def test_same_height_unchanged(self):
        """Anchor at same height as tag -- no projection needed."""
        ranges = {1: 5.0}
        result = _project_ranges_2d(ranges, {1: 0.0}, 0.0)
        self.assertAlmostEqual(result[1], 5.0)

    def test_known_projection(self):
        """Anchor at z=3m, tag at z=0, slant=5m -> horizontal=4m (3-4-5)."""
        ranges = {1: 5.0}
        result = _project_ranges_2d(ranges, {1: 3.0}, 0.0)
        self.assertAlmostEqual(result[1], 4.0, places=6)

    def test_range_smaller_than_dz_clamps(self):
        """If slant range < dz (impossible but noisy), keep original."""
        ranges = {1: 2.0}
        result = _project_ranges_2d(ranges, {1: 3.0}, 0.0)
        self.assertAlmostEqual(result[1], 2.0)

    def test_tag_z_offset(self):
        """Tag at 1m, anchor at 4m -> dz=3m, slant=5 -> horiz=4."""
        ranges = {1: 5.0}
        result = _project_ranges_2d(ranges, {1: 4.0}, 1.0)
        self.assertAlmostEqual(result[1], 4.0, places=6)

    def test_engine_with_z_projection(self):
        """Full pipeline: engine with height info should put tag at centre."""
        # Anchors at z=3m in a square, tag at z=0 in the centre
        anchors_2d = {1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)}
        anchor_z = {1: 3.0, 2: 3.0, 3: 3.0, 4: 3.0}
        tag_2d = (5.0, 5.0)
        tag_z = 0.0

        # Compute 3D slant ranges
        slant_ranges = {}
        for did, (ax, ay) in anchors_2d.items():
            dx = tag_2d[0] - ax
            dy = tag_2d[1] - ay
            dz = tag_z - anchor_z[did]
            slant_ranges[did] = math.sqrt(dx**2 + dy**2 + dz**2)

        engine = PositionEngine()
        engine.ekf_enabled = False
        engine.nlos_rejection_enabled = False
        engine.set_anchor_heights(anchor_z)
        engine.tag_z = tag_z

        result = engine.update(slant_ranges, anchors_2d, dt=0.1)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['x'], 5.0, places=1)
        self.assertAlmostEqual(result['y'], 5.0, places=1)


# ──────────────────────────────────────────────────────────────────────
# NLOS rejection
# ──────────────────────────────────────────────────────────────────────

class TestNLOSRejection(unittest.TestCase):

    def test_drops_bad_anchor(self):
        """One anchor with a big bias should be rejected."""
        anchors = {1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)}
        tag = (5.0, 5.0)
        ranges = _ranges_from(tag, anchors)
        ranges[3] += 3.0  # NLOS artifact on anchor 3

        initial = _wls_trilaterate(ranges, anchors, {d: 1 for d in anchors})
        pos, used, rejected = _nlos_rejection(
            ranges, anchors, {d: 1 for d in anchors}, initial, threshold=0.5
        )
        self.assertIn(3, rejected)
        self.assertNotIn(3, used)
        # Position should be better now
        err = math.sqrt((pos[0] - 5) ** 2 + (pos[1] - 5) ** 2)
        self.assertLess(err, 1.0)

    def test_all_good_keeps_all(self):
        """Perfect ranges → nothing rejected."""
        anchors = SQUARE_ANCHORS
        ranges = _ranges_from(TAG_POS, anchors)
        initial = _wls_trilaterate(ranges, anchors, {d: 1 for d in anchors})
        _, used, rejected = _nlos_rejection(
            ranges, anchors, {d: 1 for d in anchors}, initial, threshold=0.5
        )
        self.assertEqual(len(rejected), 0)
        self.assertEqual(len(used), 4)

    def test_needs_at_least_4_anchors(self):
        """With only 3 anchors, rejection is not attempted."""
        anchors = {1: (0, 0), 2: (10, 0), 3: (5, 10)}
        tag = (5.0, 3.0)
        ranges = _ranges_from(tag, anchors)
        ranges[1] += 5.0  # bad
        initial = _wls_trilaterate(ranges, anchors, {d: 1 for d in anchors})
        _, used, rejected = _nlos_rejection(
            ranges, anchors, {d: 1 for d in anchors}, initial, threshold=0.5
        )
        # Can't drop below 3, so nothing rejected
        self.assertEqual(len(rejected), 0)


# ──────────────────────────────────────────────────────────────────────
# EKF
# ──────────────────────────────────────────────────────────────────────

class TestEKF2D(unittest.TestCase):

    def test_converges_to_true_position(self):
        """Feed many perfect ranges — EKF should converge on tag pos."""
        anchors = SQUARE_ANCHORS
        tag = (3.0, 7.0)
        ranges = _ranges_from(tag, anchors)

        ekf = _EKF2D(0.0, 0.0, pos_var=10.0)
        for _ in range(50):
            ekf.predict(0.1, 0.1)
            ekf.update_ranges(ranges, anchors, {d: 0.01 for d in anchors})

        self.assertAlmostEqual(float(ekf.state[0]), 3.0, delta=0.2)
        self.assertAlmostEqual(float(ekf.state[1]), 7.0, delta=0.2)

    def test_covariance_shrinks(self):
        """Repeated measurements should shrink covariance."""
        anchors = SQUARE_ANCHORS
        tag = (5.0, 5.0)
        ranges = _ranges_from(tag, anchors)

        ekf = _EKF2D(5.0, 5.0, pos_var=5.0)
        initial_trace = ekf.P[0, 0] + ekf.P[1, 1]

        for _ in range(10):
            ekf.predict(0.1, 0.1)
            ekf.update_ranges(ranges, anchors, {d: 0.05 for d in anchors})

        final_trace = ekf.P[0, 0] + ekf.P[1, 1]
        self.assertLess(final_trace, initial_trace)

    def test_handles_noisy_ranges(self):
        """EKF should still be close with small Gaussian noise."""
        rng = random.Random(42)
        anchors = SQUARE_ANCHORS
        tag = (4.0, 6.0)

        ekf = _EKF2D(4.0, 6.0, pos_var=1.0)
        for _ in range(50):
            noisy = {d: _ranges_from(tag, anchors)[d] + rng.gauss(0, 0.1)
                     for d in anchors}
            ekf.predict(0.1, 0.1)
            ekf.update_ranges(noisy, anchors, {d: 0.01 for d in anchors})

        self.assertAlmostEqual(float(ekf.state[0]), 4.0, delta=0.5)
        self.assertAlmostEqual(float(ekf.state[1]), 6.0, delta=0.5)


# ──────────────────────────────────────────────────────────────────────
# PositionEngine (full pipeline)
# ──────────────────────────────────────────────────────────────────────

class TestPositionEngine(unittest.TestCase):

    def test_returns_position_with_ekf(self):
        engine = PositionEngine()
        anchors = SQUARE_ANCHORS
        ranges = _ranges_from(TAG_POS, anchors)

        result = engine.update(ranges, anchors, dt=0.1)
        self.assertIsNotNone(result)
        self.assertIn('x', result)
        self.assertIn('confidence', result)
        self.assertEqual(result['method'], 'ekf')

    def test_insufficient_ranges_returns_none(self):
        engine = PositionEngine()
        anchors = SQUARE_ANCHORS
        result = engine.update({1: 5.0, 2: 5.0}, anchors, dt=0.1)
        self.assertIsNone(result)

    def test_ekf_disabled_falls_back_to_wls(self):
        engine = PositionEngine()
        engine.ekf_enabled = False
        anchors = SQUARE_ANCHORS
        ranges = _ranges_from(TAG_POS, anchors)

        result = engine.update(ranges, anchors, dt=0.1)
        self.assertIsNotNone(result)
        self.assertIn(result['method'], ('wls', 'ls'))
        self.assertAlmostEqual(result['x'], 5.0, places=1)
        self.assertAlmostEqual(result['y'], 5.0, places=1)

    def test_nlos_rejection_in_pipeline(self):
        engine = PositionEngine()
        engine.nlos_residual_threshold = 0.5
        anchors = {1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10), 5: (5, 0)}
        tag = (5.0, 5.0)
        ranges = _ranges_from(tag, anchors)
        ranges[2] += 5.0  # big NLOS bias on anchor 2

        result = engine.update(ranges, anchors, dt=0.1)
        self.assertIsNotNone(result)
        self.assertGreater(len(result['rejected_anchors']), 0)

    def test_anchor_weights_applied(self):
        engine = PositionEngine()
        engine.set_anchor_weights({
            1: {'variance': 0.01, 'weight': 100.0},
            2: {'variance': 0.01, 'weight': 100.0},
            3: {'variance': 1.0,  'weight': 1.0},
            4: {'variance': 0.01, 'weight': 100.0},
        })
        anchors = SQUARE_ANCHORS
        ranges = _ranges_from(TAG_POS, anchors)
        result = engine.update(ranges, anchors, dt=0.1)
        self.assertIsNotNone(result)

    def test_reset_clears_ekf(self):
        engine = PositionEngine()
        anchors = SQUARE_ANCHORS
        ranges = _ranges_from(TAG_POS, anchors)
        engine.update(ranges, anchors, dt=0.1)
        self.assertIsNotNone(engine._ekf)
        engine.reset()
        self.assertIsNone(engine._ekf)

    def test_load_settings(self):
        engine = PositionEngine()
        engine.load_settings({
            'ekf_enabled': False,
            'nlos_enabled': False,
            'nlos_threshold': 1.5,
            'process_noise': 0.5,
            'range_var': 0.2,
        })
        self.assertFalse(engine.ekf_enabled)
        self.assertFalse(engine.nlos_rejection_enabled)
        self.assertAlmostEqual(engine.nlos_residual_threshold, 1.5)
        self.assertAlmostEqual(engine.ekf_process_noise, 0.5)
        self.assertAlmostEqual(engine.default_range_var, 0.2)

    def test_repeated_updates_converge(self):
        """Multiple updates should converge position + grow confidence."""
        engine = PositionEngine()
        anchors = SQUARE_ANCHORS
        ranges = _ranges_from(TAG_POS, anchors)
        for _ in range(20):
            result = engine.update(ranges, anchors, dt=0.1)
        self.assertAlmostEqual(result['x'], 5.0, delta=0.3)
        self.assertAlmostEqual(result['y'], 5.0, delta=0.3)
        self.assertGreater(result['confidence'], 0.5)


# ──────────────────────────────────────────────────────────────────────
# RTS trajectory smoother
# ──────────────────────────────────────────────────────────────────────

class TestSmoothTrajectory(unittest.TestCase):

    def test_reduces_noise(self):
        """Smoother should bring noisy positions closer to the line."""
        rng = random.Random(99)
        positions = []
        for i in range(30):
            positions.append({
                'x': float(i) + rng.gauss(0, 0.3),
                'y': 2.0 + rng.gauss(0, 0.3),
            })

        smoothed = smooth_trajectory(positions, dt=0.1,
                                     process_noise=0.1,
                                     measurement_noise=0.09)
        # Compute mean squared error vs. true line
        mse_raw = np.mean([(p['x'] - i) ** 2 + (p['y'] - 2) ** 2
                           for i, p in enumerate(positions)])
        mse_smooth = np.mean([(p['x'] - i) ** 2 + (p['y'] - 2) ** 2
                              for i, p in enumerate(smoothed)])
        self.assertLess(mse_smooth, mse_raw)

    def test_preserves_timestamps(self):
        positions = [
            {'x': 0, 'y': 0, 'ts': '2025-01-01T00:00:00'},
            {'x': 1, 'y': 0, 'ts': '2025-01-01T00:00:01'},
            {'x': 2, 'y': 0, 'ts': '2025-01-01T00:00:02'},
        ]
        smoothed = smooth_trajectory(positions)
        for orig, sm in zip(positions, smoothed):
            self.assertEqual(orig['ts'], sm['ts'])

    def test_too_few_points_returns_copy(self):
        positions = [{'x': 1, 'y': 2}]
        result = smooth_trajectory(positions)
        self.assertEqual(len(result), 1)

    def test_output_has_velocity_and_confidence(self):
        positions = [{'x': float(i), 'y': 0.0} for i in range(10)]
        smoothed = smooth_trajectory(positions, dt=0.1)
        for s in smoothed:
            self.assertIn('vx', s)
            self.assertIn('vy', s)
            self.assertIn('confidence', s)


# ──────────────────────────────────────────────────────────────────────
# build_anchor_weights
# ──────────────────────────────────────────────────────────────────────

class TestBuildAnchorWeights(unittest.TestCase):

    def test_converts_std_to_variance(self):
        corrections = {
            '1': {'std_error': 0.1, 'scale': 1.0, 'bias': 0.0},
            '2': {'std_error': 0.5, 'scale': 1.0, 'bias': 0.0},
        }
        w = build_anchor_weights(corrections)
        self.assertAlmostEqual(w[1]['variance'], 0.01, places=4)
        self.assertAlmostEqual(w[2]['variance'], 0.25, places=4)
        self.assertAlmostEqual(w[1]['weight'], 100.0, places=1)
        self.assertAlmostEqual(w[2]['weight'], 4.0, places=1)

    def test_zero_std_clamped(self):
        corrections = {'3': {'std_error': 0.0}}
        w = build_anchor_weights(corrections)
        self.assertGreater(w[3]['variance'], 0)
        self.assertGreater(w[3]['weight'], 0)

    def test_missing_std_treated_as_zero(self):
        corrections = {'4': {'scale': 1.0}}
        w = build_anchor_weights(corrections)
        self.assertIn(4, w)


# ──────────────────────────────────────────────────────────────────────
# Engine settings API routes
# ──────────────────────────────────────────────────────────────────────

class TestEngineRoutes(unittest.TestCase):

    def setUp(self):
        from uwb_web import create_app
        self.app = create_app(testing=True, db_uri='sqlite://')
        self.client = self.app.test_client()
        with self.app.app_context():
            from uwb_web.db import db
            from uwb_web.models import User
            db.create_all()
            u = User(username='admin')
            u.set_password('adminpw')
            db.session.add(u)
            db.session.commit()
        self.client.post('/login', data={'username': 'admin', 'password': 'adminpw'})

    def test_get_engine_defaults(self):
        r = self.client.get('/calibration/api/engine')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn('ekf_enabled', d)
        self.assertTrue(d['ekf_enabled'])

    def test_set_engine(self):
        r = self.client.post('/calibration/api/engine', json={
            'ekf_enabled': False,
            'nlos_enabled': True,
            'nlos_threshold': 0.8,
            'process_noise': 0.2,
            'range_var': 0.05,
        })
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d['status'], 'ok')
        self.assertFalse(d['ekf_enabled'])
        self.assertAlmostEqual(d['nlos_threshold'], 0.8)

        # Verify persisted
        r2 = self.client.get('/calibration/api/engine')
        d2 = r2.get_json()
        self.assertFalse(d2['ekf_enabled'])

    def test_engine_reset(self):
        r = self.client.post('/calibration/api/engine/reset')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['status'], 'ok')

    def test_smooth_needs_3_points(self):
        r = self.client.post('/calibration/api/smooth', json={
            'positions': [{'x': 0, 'y': 0}]
        })
        self.assertEqual(r.status_code, 400)

    def test_smooth_with_positions(self):
        positions = [{'x': float(i), 'y': 0.0} for i in range(10)]
        r = self.client.post('/calibration/api/smooth', json={
            'positions': positions
        })
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d['status'], 'ok')
        self.assertEqual(d['n'], 10)
        self.assertIn('vx', d['positions'][0])

    def test_smooth_run_not_found(self):
        r = self.client.post('/calibration/api/smooth', json={
            'source': 'run', 'run_id': 999,
        })
        self.assertEqual(r.status_code, 404)


if __name__ == '__main__':
    unittest.main()
