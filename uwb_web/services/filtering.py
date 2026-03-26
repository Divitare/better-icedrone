"""
Signal filtering service — PHASE 2 PLACEHOLDER.

Planned filters:
- Outlier rejection (IQR / threshold)
- Max-speed plausibility filter
- Moving median
- Moving average / EWMA
- Stale-value detection
"""

import logging
from collections import deque

logger = logging.getLogger(__name__)


class MeasurementFilter:
    """Base filter interface."""
    def apply(self, value):
        return value


class OutlierRejector(MeasurementFilter):
    def __init__(self, min_range=0.0, max_range=100.0):
        self.min_range = min_range
        self.max_range = max_range

    def apply(self, value):
        if value < self.min_range or value > self.max_range:
            return None
        return value


class MovingMedianFilter(MeasurementFilter):
    def __init__(self, window_size=5):
        self._buf = deque(maxlen=window_size)

    def apply(self, value):
        self._buf.append(value)
        s = sorted(self._buf)
        return s[len(s) // 2]


class MovingAverageFilter(MeasurementFilter):
    def __init__(self, window_size=5):
        self._buf = deque(maxlen=window_size)

    def apply(self, value):
        self._buf.append(value)
        return sum(self._buf) / len(self._buf)


# TODO: FilterPipeline that chains filters per device
# TODO: Speed-based plausibility filter
# TODO: EWMA filter
# TODO: Stale-value detection
