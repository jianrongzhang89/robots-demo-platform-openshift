"""Equivalent organized-cloud checks without reducing each three-value row twice."""
import numpy as np


def valid_cloud_values(points):
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    finite = np.isfinite(z)
    missing = np.isnan(z)
    return bool(np.all(finite | missing) and
                np.array_equal(np.isfinite(x), finite) and
                np.array_equal(np.isfinite(y), finite) and
                np.array_equal(np.isnan(x), missing) and
                np.array_equal(np.isnan(y), missing) and
                np.all(missing | ((z >= .15) & (z <= 5))))
