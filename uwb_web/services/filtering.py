"""
Signal filtering service for UWB range measurements.

Provides per-device filter pipelines:
- Outlier rejection (min/max range)
- Moving median for noise smoothing
- Moving average / EWMA
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


class EWMAFilter(MeasurementFilter):
    """Exponentially weighted moving average."""
    def __init__(self, alpha=0.3):
        self._alpha = alpha
        self._value = None

    def apply(self, value):
        if self._value is None:
            self._value = value
        else:
            self._value = self._alpha * value + (1 - self._alpha) * self._value
        return self._value


class FilterPipeline:
    """Chain multiple filters per device. Returns filtered value or None (rejected)."""

    def __init__(self, filters=None):
        self.filters = filters or []

    def apply(self, value):
        for f in self.filters:
            value = f.apply(value)
            if value is None:
                return None
        return value


class DeviceFilterBank:
    """Manages per-device filter pipelines for range measurements."""

    def __init__(self, min_range=0.05, max_range=50.0, median_window=5):
        self._pipelines = {}
        self._min_range = min_range
        self._max_range = max_range
        self._median_window = median_window

    def _get_pipeline(self, device_id):
        if device_id not in self._pipelines:
            self._pipelines[device_id] = FilterPipeline([
                OutlierRejector(self._min_range, self._max_range),
                MovingMedianFilter(self._median_window),
            ])
        return self._pipelines[device_id]

    def filter_range(self, device_id, range_m):
        """Apply per-device filter chain. Returns filtered range or None."""
        return self._get_pipeline(device_id).apply(range_m)
