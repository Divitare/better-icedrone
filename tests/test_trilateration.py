"""Tests for trilateration and filtering."""

import unittest
import math
from uwb_web.services.trilateration import estimate_position_2d, estimate_position_3d
from uwb_web.services.filtering import (
    OutlierRejector, MovingMedianFilter, DeviceFilterBank, FilterPipeline,
)


class TestTrilateration2D(unittest.TestCase):

    def test_three_anchors_origin(self):
        """Tag at origin with 3 anchors at known positions."""
        anchors = {1: (3, 0), 2: (0, 4), 3: (-3, 0)}
        ranges = {1: 3.0, 2: 4.0, 3: 3.0}
        pos = estimate_position_2d(ranges, anchors)
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 0.0, places=2)
        self.assertAlmostEqual(pos[1], 0.0, places=2)

    def test_three_anchors_offset(self):
        """Tag at (2, 1) with 3 anchors."""
        anchors = {1: (0, 0), 2: (5, 0), 3: (0, 5)}
        # Expected distances from (2,1)
        ranges = {
            1: math.sqrt(4 + 1),   # sqrt(5)
            2: math.sqrt(9 + 1),   # sqrt(10)
            3: math.sqrt(4 + 16),  # sqrt(20)
        }
        pos = estimate_position_2d(ranges, anchors)
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 2.0, places=2)
        self.assertAlmostEqual(pos[1], 1.0, places=2)

    def test_insufficient_anchors(self):
        """Returns None with < 3 anchors."""
        anchors = {1: (0, 0), 2: (5, 0)}
        ranges = {1: 3.0, 2: 4.0}
        self.assertIsNone(estimate_position_2d(ranges, anchors))

    def test_four_anchors_overdetermined(self):
        """Overdetermined with 4 anchors should still work."""
        anchors = {1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)}
        # Tag at (5, 5) -> all distances = sqrt(50)
        d = math.sqrt(50)
        ranges = {1: d, 2: d, 3: d, 4: d}
        pos = estimate_position_2d(ranges, anchors)
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 5.0, places=1)
        self.assertAlmostEqual(pos[1], 5.0, places=1)

    def test_ignores_missing_range(self):
        """Anchors without range data are ignored."""
        anchors = {1: (0, 0), 2: (5, 0), 3: (0, 5)}
        ranges = {1: 2.0, 2: 3.0}  # only 2 ranges
        self.assertIsNone(estimate_position_2d(ranges, anchors))

    def test_zero_range_ignored(self):
        """Zero or negative ranges should be rejected."""
        anchors = {1: (0, 0), 2: (5, 0), 3: (0, 5)}
        ranges = {1: 0.0, 2: 3.0, 3: 4.0}  # 0 range -> ignored
        self.assertIsNone(estimate_position_2d(ranges, anchors))


class TestTrilateration3D(unittest.TestCase):

    def test_four_anchors_origin(self):
        """Tag at origin with 4 anchors."""
        anchors = {1: (3, 0, 0), 2: (0, 4, 0), 3: (-3, 0, 0), 4: (0, 0, 2)}
        ranges = {1: 3.0, 2: 4.0, 3: 3.0, 4: 2.0}
        pos = estimate_position_3d(ranges, anchors)
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 0.0, places=1)
        self.assertAlmostEqual(pos[1], 0.0, places=1)
        self.assertAlmostEqual(pos[2], 0.0, places=1)

    def test_insufficient_anchors(self):
        anchors = {1: (0, 0, 0), 2: (5, 0, 0), 3: (0, 5, 0)}
        ranges = {1: 3, 2: 4, 3: 3}
        self.assertIsNone(estimate_position_3d(ranges, anchors))


class TestFiltering(unittest.TestCase):

    def test_outlier_rejector(self):
        f = OutlierRejector(0.1, 50.0)
        self.assertIsNone(f.apply(0.0))
        self.assertIsNone(f.apply(100.0))
        self.assertEqual(f.apply(5.0), 5.0)

    def test_moving_median(self):
        f = MovingMedianFilter(3)
        self.assertEqual(f.apply(1), 1)
        self.assertEqual(f.apply(100), 100)  # [1, 100] -> median is 100 (idx 1 of sorted)
        self.assertEqual(f.apply(2), 2)     # [1, 100, 2] sorted [1, 2, 100] -> median=2

    def test_device_filter_bank(self):
        bank = DeviceFilterBank(min_range=0.1, max_range=50.0, median_window=3)
        # Valid range
        r = bank.filter_range(1, 5.0)
        self.assertIsNotNone(r)
        # Outlier
        r = bank.filter_range(1, 0.0)
        self.assertIsNone(r)

    def test_pipeline(self):
        p = FilterPipeline([OutlierRejector(0.1, 50.0)])
        self.assertEqual(p.apply(3.0), 3.0)
        self.assertIsNone(p.apply(0.0))


if __name__ == '__main__':
    unittest.main()
