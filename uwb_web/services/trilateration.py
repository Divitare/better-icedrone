"""
Trilateration service — compute tag position from UWB range measurements.

Uses linear least-squares (reference-anchor subtraction) to solve for
the tag position given range measurements to anchors at known coordinates.

2D requires >= 3 anchors, 3D requires >= 4 anchors.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


def estimate_position_2d(ranges, anchors):
    """
    Estimate 2D position from range measurements using least-squares.

    Args:
        ranges: dict {device_id: range_m}
        anchors: dict {device_id: (x, y)}

    Returns:
        (x, y) tuple or None if insufficient data / solver fails.
    """
    available = [did for did in ranges if did in anchors and ranges[did] is not None and ranges[did] > 0]
    if len(available) < 3:
        return None

    try:
        # Use first anchor as reference to linearise
        ref = available[0]
        x0, y0 = anchors[ref]
        r0 = ranges[ref]

        A_rows = []
        b_rows = []
        for did in available[1:]:
            xi, yi = anchors[did]
            ri = ranges[did]
            A_rows.append([2 * (xi - x0), 2 * (yi - y0)])
            b_rows.append(r0**2 - ri**2 + xi**2 - x0**2 + yi**2 - y0**2)

        A = np.array(A_rows, dtype=float)
        b = np.array(b_rows, dtype=float)

        # Solve via least-squares
        result, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)

        x, y = float(result[0]), float(result[1])

        # Sanity check — reject positions absurdly far from anchor centroid
        cx = np.mean([anchors[d][0] for d in available])
        cy = np.mean([anchors[d][1] for d in available])
        max_range = max(ranges[d] for d in available)
        if abs(x - cx) > max_range * 3 or abs(y - cy) > max_range * 3:
            logger.debug("Position (%.2f, %.2f) rejected — too far from anchors", x, y)
            return None

        return (round(x, 4), round(y, 4))

    except Exception as e:
        logger.warning("2D trilateration failed: %s", e)
        return None


def estimate_position_3d(ranges, anchors):
    """
    Estimate 3D position from range measurements using least-squares.

    Args:
        ranges: dict {device_id: range_m}
        anchors: dict {device_id: (x, y, z)}

    Returns:
        (x, y, z) tuple or None if insufficient data / solver fails.
    """
    available = [did for did in ranges if did in anchors and ranges[did] is not None and ranges[did] > 0]
    if len(available) < 4:
        return None

    try:
        ref = available[0]
        x0, y0, z0 = anchors[ref]
        r0 = ranges[ref]

        A_rows = []
        b_rows = []
        for did in available[1:]:
            xi, yi, zi = anchors[did]
            ri = ranges[did]
            A_rows.append([2 * (xi - x0), 2 * (yi - y0), 2 * (zi - z0)])
            b_rows.append(r0**2 - ri**2 + xi**2 - x0**2 + yi**2 - y0**2 + zi**2 - z0**2)

        A = np.array(A_rows, dtype=float)
        b = np.array(b_rows, dtype=float)

        result, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)
        x, y, z = float(result[0]), float(result[1]), float(result[2])

        cx = np.mean([anchors[d][0] for d in available])
        cy = np.mean([anchors[d][1] for d in available])
        cz = np.mean([anchors[d][2] for d in available])
        max_range = max(ranges[d] for d in available)
        if (abs(x - cx) > max_range * 3 or abs(y - cy) > max_range * 3
                or abs(z - cz) > max_range * 3):
            logger.debug("3D position rejected — too far from anchors")
            return None

        return (round(x, 4), round(y, 4), round(z, 4))

    except Exception as e:
        logger.warning("3D trilateration failed: %s", e)
        return None
