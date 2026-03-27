"""Tests for calibration service and routes."""

import unittest
import os
import json
import math

import numpy as np

from uwb_web import create_app
from uwb_web.db import db
from uwb_web.models import User, Device, CalibrationRun, CalibrationPoint
from uwb_web.services.calibration import (
    compute_corrections,
    compute_position_stats,
    apply_range_correction,
    correct_ranges,
    get_active_corrections,
    invalidate_corrections_cache,
)


# ──────────────────────────────────────────────────────────────────────
# Pure-function tests (no Flask app needed)
# ──────────────────────────────────────────────────────────────────────

class TestComputeCorrections(unittest.TestCase):

    def test_perfect_data_returns_unit_scale_zero_bias(self):
        """When measured == true, scale ≈ 1 and bias ≈ 0."""
        anchors = {
            1: {'hex': 'AA', 'x': 0, 'y': 0, 'z': 0},
            2: {'hex': 'BB', 'x': 3, 'y': 0, 'z': 0},
        }
        points = []
        for tx, ty in [(1, 0), (2, 0), (1.5, 1)]:
            ranges = {}
            for did, a in anchors.items():
                true_r = math.sqrt((tx - a['x'])**2 + (ty - a['y'])**2)
                ranges[a['hex']] = {'device_id': did, 'mean': true_r}
            points.append({
                'true_x': tx, 'true_y': ty, 'true_z': 0,
                'ranges': ranges,
            })
        corr = compute_corrections(points, anchors)
        for did in anchors:
            self.assertIn(did, corr)
            self.assertAlmostEqual(corr[did]['scale'], 1.0, places=3)
            self.assertAlmostEqual(corr[did]['bias'], 0.0, places=3)

    def test_known_bias(self):
        """Constant offset detected as bias."""
        anchors = {1: {'hex': 'AA', 'x': 0, 'y': 0, 'z': 0}}
        BIAS = 0.5
        points = []
        for tx in [1, 2, 3, 4]:
            true_r = float(tx)
            points.append({
                'true_x': tx, 'true_y': 0, 'true_z': 0,
                'ranges': {'AA': {'device_id': 1, 'mean': true_r + BIAS}},
            })
        corr = compute_corrections(points, anchors)
        self.assertAlmostEqual(corr[1]['bias'], BIAS, places=3)
        self.assertAlmostEqual(corr[1]['scale'], 1.0, places=3)

    def test_known_scale(self):
        """Linear scaling detected."""
        anchors = {1: {'hex': 'AA', 'x': 0, 'y': 0, 'z': 0}}
        SCALE = 1.1
        points = []
        for tx in [1, 2, 3, 4]:
            true_r = float(tx)
            points.append({
                'true_x': tx, 'true_y': 0, 'true_z': 0,
                'ranges': {'AA': {'device_id': 1, 'mean': true_r * SCALE}},
            })
        corr = compute_corrections(points, anchors)
        self.assertAlmostEqual(corr[1]['scale'], SCALE, places=3)
        self.assertAlmostEqual(corr[1]['bias'], 0.0, places=3)

    def test_too_few_samples_skipped(self):
        """Anchor with only 1 sample is skipped."""
        anchors = {1: {'hex': 'AA', 'x': 0, 'y': 0, 'z': 0}}
        points = [{'true_x': 1, 'true_y': 0, 'true_z': 0,
                    'ranges': {'AA': {'device_id': 1, 'mean': 1.0}}}]
        corr = compute_corrections(points, anchors)
        self.assertEqual(corr, {})


class TestComputePositionStats(unittest.TestCase):

    def test_zero_error(self):
        pts = [
            {'true_x': 1, 'true_y': 2, 'true_z': 0, 'uwb_x': 1, 'uwb_y': 2, 'uwb_z': 0},
            {'true_x': 3, 'true_y': 4, 'true_z': 0, 'uwb_x': 3, 'uwb_y': 4, 'uwb_z': 0},
        ]
        stats = compute_position_stats(pts)
        self.assertAlmostEqual(stats['rmse'], 0.0)
        self.assertEqual(stats['n_points'], 2)

    def test_known_error(self):
        pts = [
            {'true_x': 0, 'true_y': 0, 'true_z': 0, 'uwb_x': 0.3, 'uwb_y': 0.4, 'uwb_z': 0},
        ]
        stats = compute_position_stats(pts)
        self.assertAlmostEqual(stats['rmse'], 0.5, places=3)

    def test_missing_uwb(self):
        pts = [{'true_x': 1, 'true_y': 2, 'true_z': 0, 'uwb_x': None, 'uwb_y': None}]
        stats = compute_position_stats(pts)
        self.assertEqual(stats['n_points'], 0)


class TestApplyRangeCorrection(unittest.TestCase):

    def test_identity(self):
        self.assertAlmostEqual(apply_range_correction(5.0, 0.0, 1.0), 5.0)

    def test_bias_only(self):
        self.assertAlmostEqual(apply_range_correction(5.5, 0.5, 1.0), 5.0)

    def test_scale_only(self):
        self.assertAlmostEqual(apply_range_correction(5.5, 0.0, 1.1), 5.0, places=3)

    def test_degenerate_scale(self):
        # scale near zero → no correction
        self.assertAlmostEqual(apply_range_correction(5.0, 1.0, 0.001), 5.0)


class TestCorrectRanges(unittest.TestCase):

    def test_applies_corrections(self):
        ranges = {1: 5.5, 2: 3.0}
        corrections = {1: {'bias': 0.5, 'scale': 1.0}}
        result = correct_ranges(ranges, corrections)
        self.assertAlmostEqual(result[1], 5.0)
        self.assertAlmostEqual(result[2], 3.0)  # no correction for did=2

    def test_empty_corrections_passthrough(self):
        ranges = {1: 5.0}
        result = correct_ranges(ranges, {})
        self.assertEqual(result, ranges)

    def test_none_value_preserved(self):
        ranges = {1: None}
        result = correct_ranges(ranges, {1: {'bias': 0.5, 'scale': 1.0}})
        self.assertIsNone(result[1])


# ──────────────────────────────────────────────────────────────────────
# Route tests (need Flask app)
# ──────────────────────────────────────────────────────────────────────

class TestCalibrationRoutes(unittest.TestCase):

    def setUp(self):
        os.environ['UWB_CONFIG'] = ''
        self.app = create_app(testing=True, db_uri='sqlite://')
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            admin = User(username='admin', is_admin=True)
            admin.set_password('adminpw')
            db.session.add(admin)
            # Add some anchors
            for i, (hx, x, y) in enumerate(
                [('A1', 0.0, 0.0), ('A2', 5.0, 0.0), ('A3', 2.5, 4.0)], start=1
            ):
                db.session.add(Device(
                    short_addr_hex=hx, is_anchor=True,
                    x=x, y=y, z=0.0, is_active=True,
                ))
            db.session.commit()
        self.client.post('/login', data={'username': 'admin', 'password': 'adminpw'})
        # Reset the runner singleton for isolation
        import uwb_web.routes.calibration as cal_mod
        cal_mod._runner = None

    def tearDown(self):
        import uwb_web.routes.calibration as cal_mod
        cal_mod._runner = None
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_page_loads(self):
        r = self.client.get('/calibration/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Calibration', r.data)

    def test_status_idle(self):
        r = self.client.get('/calibration/api/status')
        data = r.get_json()
        self.assertEqual(data['status'], 'idle')

    def test_runs_empty(self):
        r = self.client.get('/calibration/api/runs')
        self.assertEqual(r.get_json(), [])

    def test_toggle_corrections(self):
        r = self.client.post('/calibration/api/toggle',
                             json={'enabled': True})
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['enabled'])
        # Check DB
        r2 = self.client.get('/calibration/api/corrections')
        self.assertTrue(r2.get_json()['enabled'])

    def test_toggle_off(self):
        self.client.post('/calibration/api/toggle', json={'enabled': True})
        self.client.post('/calibration/api/toggle', json={'enabled': False})
        r = self.client.get('/calibration/api/corrections')
        self.assertFalse(r.get_json()['enabled'])

    def test_apply_missing_run(self):
        r = self.client.post('/calibration/api/apply', json={'run_id': 999})
        self.assertEqual(r.status_code, 404)

    def test_apply_run_with_results(self):
        with self.app.app_context():
            run = CalibrationRun(
                name='Test Run', status='completed',
                origin_x=0, origin_y=0, origin_z=0,
                dwell_seconds=3, speed_mm_s=10,
                results_json=json.dumps({
                    'corrections': {
                        '1': {'hex': 'A1', 'bias': 0.1, 'scale': 1.02,
                               'mean_error': 0.01, 'std_error': 0.005, 'n_samples': 5},
                    },
                    'stats_before': {'rmse': 0.15, 'mean_error': 0.12, 'max_error': 0.2, 'n_points': 5},
                    'stats_after': {'rmse': 0.05, 'mean_error': 0.04, 'max_error': 0.08, 'n_points': 5},
                }),
            )
            db.session.add(run)
            db.session.commit()
            run_id = run.id
        r = self.client.post('/calibration/api/apply', json={'run_id': run_id})
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')
        # Verify corrections are active
        r2 = self.client.get('/calibration/api/corrections')
        d2 = r2.get_json()
        self.assertTrue(d2['enabled'])
        self.assertIn('1', d2['corrections'])

    def test_run_detail(self):
        with self.app.app_context():
            run = CalibrationRun(
                name='Detail Run', status='completed',
                origin_x=1.0, origin_y=2.0, origin_z=0.0,
                dwell_seconds=3, speed_mm_s=10,
                results_json=json.dumps({'corrections': {}, 'stats_before': {}, 'stats_after': {}}),
            )
            db.session.add(run)
            db.session.flush()
            db.session.add(CalibrationPoint(
                run_id=run.id, point_index=0,
                true_x=1.0, true_y=2.0, true_z=0.0,
                uwb_x=1.05, uwb_y=2.03, uwb_z=0.0,
                error_m=0.058,
            ))
            db.session.commit()
            run_id = run.id

        r = self.client.get(f'/calibration/api/runs/{run_id}')
        data = r.get_json()
        self.assertEqual(data['name'], 'Detail Run')
        self.assertEqual(len(data['points']), 1)
        self.assertAlmostEqual(data['points'][0]['true_x'], 1.0)

    def test_runs_list_returns_history(self):
        with self.app.app_context():
            for i in range(3):
                db.session.add(CalibrationRun(
                    name=f'Run {i}', status='completed',
                    origin_x=0, origin_y=0, origin_z=0,
                    dwell_seconds=3, speed_mm_s=10,
                ))
            db.session.commit()
        r = self.client.get('/calibration/api/runs')
        data = r.get_json()
        self.assertEqual(len(data), 3)

    def test_cancel_when_not_running(self):
        r = self.client.post('/calibration/api/cancel')
        self.assertEqual(r.status_code, 409)

    def test_start_empty_grid(self):
        r = self.client.post('/calibration/api/start', json={
            'grid': {'x': {'start': 0, 'spacing': 100, 'count': 0}},
        })
        self.assertEqual(r.status_code, 400)


class TestGetActiveCorrections(unittest.TestCase):

    def setUp(self):
        os.environ['UWB_CONFIG'] = ''
        self.app = create_app(testing=True, db_uri='sqlite://')
        with self.app.app_context():
            db.create_all()
        invalidate_corrections_cache()

    def tearDown(self):
        invalidate_corrections_cache()
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_returns_empty_when_disabled(self):
        result = get_active_corrections(self.app)
        self.assertEqual(result, {})

    def test_returns_corrections_when_enabled(self):
        with self.app.app_context():
            from uwb_web.services.config_service import set_config
            set_config('cal_corrections', json.dumps({
                '1': {'bias': 0.1, 'scale': 1.05},
            }))
            set_config('cal_corrections_enabled', 'true')
        invalidate_corrections_cache()
        result = get_active_corrections(self.app)
        self.assertIn(1, result)
        self.assertAlmostEqual(result[1]['bias'], 0.1)


if __name__ == '__main__':
    unittest.main()
