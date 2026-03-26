"""
Trilateration service — PHASE 2 PLACEHOLDER.

Will implement 3D position estimation from UWB range measurements.

Required:
- At least 4 anchor positions (x, y, z) stored in devices table
- Concurrent range measurements from tag to each anchor
- Outlier rejection before solving

Candidate algorithms:
- Linear least-squares (Chan's algorithm)
- Nonlinear least-squares (Levenberg-Marquardt)
- Extended Kalman Filter for smooth tracking
"""

import logging

logger = logging.getLogger(__name__)


def estimate_position_3d(ranges, anchors):
    """
    Estimate 3D position from range measurements to known anchors.

    Args:
        ranges: dict {device_id: range_m}
        anchors: dict {device_id: (x, y, z)}

    Returns:
        (x, y, z) or None if insufficient data.
    """
    available = [did for did in ranges if did in anchors]
    if len(available) < 4:
        logger.debug("Need >= 4 anchors for 3D, have %d", len(available))
        return None
    # TODO: implement trilateration solver
    return None


def estimate_position_2d(ranges, anchors):
    """
    Estimate 2D position from range measurements.

    Args:
        ranges: dict {device_id: range_m}
        anchors: dict {device_id: (x, y)}

    Returns:
        (x, y) or None if insufficient data.
    """
    available = [did for did in ranges if did in anchors]
    if len(available) < 3:
        logger.debug("Need >= 3 anchors for 2D, have %d", len(available))
        return None
    # TODO: implement 2D trilateration solver
    return None
