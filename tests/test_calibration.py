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
    estimate_rigid_transform,
    apply_rigid_transform,
    refine_anchor_positions,
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
# Rigid transform tests
# ──────────────────────────────────────────────────────────────────────

class TestEstimateRigidTransform(unittest.TestCase):

    def test_identity_transform(self):
        """When motion mm == UWB m numerically (scale=1), rotation ≈ 0."""
        pts = [[0, 0], [1, 0], [0, 1], [1, 1]]
        result = estimate_rigid_transform(pts, pts)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['rotation_deg'], 0.0, places=1)
        self.assertAlmostEqual(result['scale'], 1.0, places=4)
        self.assertAlmostEqual(result['rmse_m'], 0.0, places=6)

    def test_known_translation(self):
        """Pure translation (scale=1) is recovered."""
        motion = [[0, 0], [100, 0], [0, 100], [100, 100]]
        uwb = [[tx + 5.0, ty + 3.0] for tx, ty in motion]
        result = estimate_rigid_transform(motion, uwb)
        self.assertAlmostEqual(result['rotation_deg'], 0.0, places=1)
        self.assertAlmostEqual(result['scale'], 1.0, places=4)
        self.assertAlmostEqual(result['translation_m'][0], 5.0, places=3)
        self.assertAlmostEqual(result['translation_m'][1], 3.0, places=3)
        self.assertAlmostEqual(result['rmse_m'], 0.0, places=6)

    def test_mm_to_m_scale(self):
        """Motion in mm, UWB in m → scale ≈ 0.001."""
        motion_mm = [[0, 0], [1000, 0], [0, 1000], [1000, 1000]]
        uwb_m = [[0, 0], [1, 0], [0, 1], [1, 1]]
        result = estimate_rigid_transform(motion_mm, uwb_m)
        self.assertAlmostEqual(result['scale'], 0.001, places=5)
        self.assertAlmostEqual(result['rmse_m'], 0.0, places=5)

    def test_known_90deg_rotation(self):
        """90° rotation is recovered."""
        motion = [[0, 0], [1, 0], [0, 1], [1, 1]]
        # Rotate 90° CCW: (x, y) → (-y, x)
        uwb = [[-y, x] for x, y in motion]
        result = estimate_rigid_transform(motion, uwb)
        self.assertAlmostEqual(abs(result['rotation_deg']), 90.0, places=1)
        self.assertAlmostEqual(result['scale'], 1.0, places=4)
        self.assertAlmostEqual(result['rmse_m'], 0.0, places=5)

    def test_combined_scale_rotation_translation(self):
        """Combined transform is recovered."""
        motion_mm = [[0, 0], [1000, 0], [500, 500]]
        # scale 0.001, 45° rotation, translation (2, 3)
        angle = math.radians(45)
        s = 0.001
        tx, ty = 2.0, 3.0
        uwb_m = []
        for mx, my in motion_mm:
            ux = s * (math.cos(angle) * mx - math.sin(angle) * my) + tx
            uy = s * (math.sin(angle) * mx + math.cos(angle) * my) + ty
            uwb_m.append([ux, uy])
        result = estimate_rigid_transform(motion_mm, uwb_m)
        self.assertAlmostEqual(result['rotation_deg'], 45.0, places=1)
        self.assertAlmostEqual(result['scale'], 0.001, places=5)
        self.assertAlmostEqual(result['translation_m'][0], tx, places=3)
        self.assertAlmostEqual(result['translation_m'][1], ty, places=3)
        self.assertAlmostEqual(result['rmse_m'], 0.0, places=5)

    def test_returns_none_insufficient_points(self):
        """Fewer than 3 points returns None."""
        result = estimate_rigid_transform([[0, 0], [1, 0]], [[0, 0], [1, 0]])
        self.assertIsNone(result)

    def test_per_point_errors(self):
        """per_point_error_m has one entry per point."""
        pts = [[0, 0], [1, 0], [0, 1], [1, 1]]
        result = estimate_rigid_transform(pts, pts)
        self.assertEqual(len(result['per_point_error_m']), 4)
        for e in result['per_point_error_m']:
            self.assertAlmostEqual(e, 0.0, places=6)


class TestApplyRigidTransform(unittest.TestCase):

    def test_identity(self):
        """Identity R, zero t, scale 1 returns same points."""
        pts = [[100, 200], [300, 400]]
        R = [[1, 0], [0, 1]]
        t = [0, 0]
        out = apply_rigid_transform(pts, R, t, 1.0)
        np.testing.assert_allclose(out, pts, atol=1e-9)

    def test_scale_only(self):
        """Scale 0.001 converts mm to m."""
        pts = [[1000, 2000]]
        R = [[1, 0], [0, 1]]
        t = [0, 0]
        out = apply_rigid_transform(pts, R, t, 0.001)
        np.testing.assert_allclose(out, [[1.0, 2.0]], atol=1e-9)

    def test_roundtrip(self):
        """estimate + apply should produce the UWB positions."""
        motion_mm = [[0, 0], [500, 0], [0, 300], [500, 300]]
        uwb_m = [[1, 2], [1.5, 2], [1, 2.3], [1.5, 2.3]]
        tf = estimate_rigid_transform(motion_mm, uwb_m)
        out = apply_rigid_transform(motion_mm, tf['R'], tf['t'], tf['scale'])
        np.testing.assert_allclose(out, uwb_m, atol=1e-4)


class TestRefineAnchorPositions(unittest.TestCase):

    def _make_range_data(self, tag_positions, anchor_positions):
        """Build range_data from true tag–anchor distances."""
        rd = []
        for tx, ty in tag_positions:
            obs = {}
            for aid, (ax, ay) in anchor_positions.items():
                d = math.sqrt((tx - ax)**2 + (ty - ay)**2)
                obs[aid] = {'mean': d, 'weight': 1.0}
            rd.append(obs)
        return rd

    def test_perfect_data_converges(self):
        """With perfect ranges from true anchors, refinement stays put."""
        true_anchors = {1: (0, 0), 2: (5, 0), 3: (2.5, 4)}
        tags = [(1, 1), (2, 2), (3, 1), (4, 3)]
        rd = self._make_range_data(tags, true_anchors)
        result = refine_anchor_positions(tags, rd, true_anchors)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['rmse_before'], 0.0, places=4)
        self.assertAlmostEqual(result['rmse_after'], 0.0, places=4)
        for aid in true_anchors:
            self.assertAlmostEqual(result['anchors'][aid]['dx'], 0.0, places=3)
            self.assertAlmostEqual(result['anchors'][aid]['dy'], 0.0, places=3)

    def test_offset_anchors_are_corrected(self):
        """Starting from offset anchors, refinement moves towards truth."""
        true_anchors = {1: (0, 0), 2: (5, 0), 3: (2.5, 4)}
        offset_anchors = {1: (0.05, -0.03), 2: (5.1, 0.04), 3: (2.55, 3.92)}
        tags = [(1, 1), (2, 2), (3, 1), (4, 3), (1.5, 0.5), (3.5, 2.5)]
        rd = self._make_range_data(tags, true_anchors)  # ranges from TRUE positions
        result = refine_anchor_positions(tags, rd, offset_anchors)
        self.assertIsNotNone(result)
        # RMSE should improve
        self.assertLess(result['rmse_after'], result['rmse_before'])
        # Anchors should move towards true positions
        for aid in true_anchors:
            tx, ty = true_anchors[aid]
            rx, ry = result['anchors'][aid]['x'], result['anchors'][aid]['y']
            self.assertAlmostEqual(rx, tx, places=2)
            self.assertAlmostEqual(ry, ty, places=2)

    def test_returns_none_too_few_points(self):
        """Fewer than 2 tag positions returns None."""
        result = refine_anchor_positions(
            [(1, 1)], [{}], {1: (0, 0), 2: (5, 0)})
        self.assertIsNone(result)

    def test_returns_none_too_few_observations(self):
        """Not enough observations relative to anchors returns None."""
        tags = [(1, 1), (2, 2)]
        rd = [{1: {'mean': 1.0, 'weight': 1.0}}, {}]
        result = refine_anchor_positions(tags, rd, {1: (0, 0), 2: (5, 0), 3: (2.5, 4)})
        self.assertIsNone(result)


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


class TestAlignmentRoutes(unittest.TestCase):
    """Test auto-origin and anchor-refinement API endpoints."""

    def setUp(self):
        os.environ['UWB_CONFIG'] = ''
        self.app = create_app(testing=True, db_uri='sqlite://')
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            admin = User(username='admin', is_admin=True)
            admin.set_password('adminpw')
            db.session.add(admin)
            # Add anchors with known positions
            for i, (hx, x, y) in enumerate(
                [('A1', 0.0, 0.0), ('A2', 5.0, 0.0), ('A3', 2.5, 4.0)], start=1
            ):
                db.session.add(Device(
                    short_addr_hex=hx, is_anchor=True,
                    x=x, y=y, z=0.0, is_active=True,
                ))
            db.session.commit()
        self.client.post('/login', data={'username': 'admin', 'password': 'adminpw'})
        import uwb_web.routes.calibration as cal_mod
        cal_mod._runner = None

    def tearDown(self):
        import uwb_web.routes.calibration as cal_mod
        cal_mod._runner = None
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def _create_run_with_grid(self):
        """Create a completed run with a 3×3 grid, UWB data, and ranges."""
        with self.app.app_context():
            # Build a 3×3 grid in mm
            grid = []
            for iy in range(3):
                for ix in range(3):
                    grid.append({'x': ix * 500, 'y': iy * 500, 'z': 0})

            run = CalibrationRun(
                name='Grid Run', status='completed',
                origin_x=0, origin_y=0, origin_z=0,
                dwell_seconds=3, speed_mm_s=10,
                grid_config_json=json.dumps(grid),
                results_json=json.dumps({
                    'corrections': {}, 'stats_before': {}, 'stats_after': {},
                }),
            )
            db.session.add(run)
            db.session.flush()

            anchors = {1: (0, 0), 2: (5, 0), 3: (2.5, 4)}
            devices = {d.id: d for d in Device.query.filter_by(is_anchor=True).all()}

            for i, gp in enumerate(grid):
                # True UWB position: motion mm * 0.001 + offset (1.0, 2.0)
                ux = gp['x'] * 0.001 + 1.0
                uy = gp['y'] * 0.001 + 2.0
                # Build ranges from true anchor positions
                ranges = {}
                for d in devices.values():
                    dist = math.sqrt((ux - d.x)**2 + (uy - d.y)**2)
                    ranges[d.short_addr_hex] = {
                        'device_id': d.id, 'mean': dist, 'std': 0.01, 'count': 50,
                    }
                db.session.add(CalibrationPoint(
                    run_id=run.id, point_index=i,
                    true_x=ux, true_y=uy, true_z=0.0,
                    uwb_x=ux, uwb_y=uy, uwb_z=0.0,
                    error_m=0.0,
                    ranges_json=json.dumps(ranges),
                ))
            db.session.commit()
            return run.id

    def test_auto_origin_missing_run(self):
        r = self.client.post('/calibration/api/auto-origin', json={'run_id': 999})
        self.assertEqual(r.status_code, 404)

    def test_auto_origin_no_run_id(self):
        r = self.client.post('/calibration/api/auto-origin', json={})
        self.assertEqual(r.status_code, 400)

    def test_auto_origin_success(self):
        run_id = self._create_run_with_grid()
        r = self.client.post('/calibration/api/auto-origin', json={'run_id': run_id})
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('rotation_deg', data)
        self.assertIn('scale', data)
        self.assertIn('translation_m', data)
        self.assertIn('rmse_m', data)
        # Scale should be close to 0.001 (mm → m)
        self.assertAlmostEqual(data['scale'], 0.001, places=4)

    def test_auto_origin_get_after_post(self):
        run_id = self._create_run_with_grid()
        self.client.post('/calibration/api/auto-origin', json={'run_id': run_id})
        r = self.client.get('/calibration/api/auto-origin')
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('R', data)
        self.assertIn('scale', data)

    def test_auto_origin_get_no_transform(self):
        r = self.client.get('/calibration/api/auto-origin')
        data = r.get_json()
        self.assertEqual(data['status'], 'none')

    def test_refine_anchors_success(self):
        run_id = self._create_run_with_grid()
        r = self.client.post('/calibration/api/refine-anchors', json={'run_id': run_id})
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('anchors', data)
        self.assertIn('rmse_before', data)
        self.assertIn('rmse_after', data)
        self.assertIn('transform', data)

    def test_refine_anchors_missing_run(self):
        r = self.client.post('/calibration/api/refine-anchors', json={'run_id': 999})
        self.assertEqual(r.status_code, 404)

    def test_apply_refined_anchors(self):
        r = self.client.post('/calibration/api/apply-refined-anchors', json={
            'anchors': {'1': {'x': 0.05, 'y': -0.02}}
        })
        data = r.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['updated'], 1)
        # Verify DB was updated
        with self.app.app_context():
            d = Device.query.get(1)
            self.assertAlmostEqual(d.x, 0.05)
            self.assertAlmostEqual(d.y, -0.02)

    def test_apply_refined_anchors_empty(self):
        r = self.client.post('/calibration/api/apply-refined-anchors', json={'anchors': {}})
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
