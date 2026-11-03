"""Fit image-to-ground transforms from control points.

    m = fit("projective", src, dst)   # src, dst: (N, 2) arrays
    m.predict(points); m.jacobian(points)
    loo_residuals("poly2", src, dst)  # distance of each point from the fit made without it

Methods and the fewest points each needs: affine 3, projective 4, poly2 6, poly3 10.
Coordinates are normalised (centred, scaled to unit RMS radius) before solving. Too few points,
or points too close to a line to determine the transform, raise ValueError instead of returning a fit.
"""

import numpy as np

MIN_POINTS = {"affine": 3, "projective": 4, "poly2": 6, "poly3": 10}
DEGREE = {"affine": 1, "poly2": 2, "poly3": 3}
RCOND = 1e-9


def _norm(p):
    c = p.mean(axis=0)
    s = np.sqrt(((p - c) ** 2).sum(axis=1).mean())
    if s == 0:
        raise ValueError("all points coincide")
    s = np.sqrt(2.0) / s
    T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1.0]])
    return T


def _h(T, p):
    q = np.column_stack([p, np.ones(len(p))]) @ T.T
    return q[:, :2] / q[:, 2:]


def _poly_features(p, degree):
    x, y = p[:, 0], p[:, 1]
    cols = [x**i * y**j for d in range(degree + 1) for j in range(d + 1) for i in [d - j]]
    return np.column_stack(cols)


class Fit:
    def __init__(self, method, Ts, Td, params):
        self.method, self.Ts, self.Td, self.params = method, Ts, Td, params

    def predict(self, p):
        p = np.atleast_2d(np.asarray(p, float))
        q = _h(self.Ts, p)
        if self.method == "projective":
            r = _h(self.params, q)
        else:
            r = _poly_features(q, DEGREE[self.method]) @ self.params
        return _h(np.linalg.inv(self.Td), r)

    def jacobian(self, p, eps=0.5):
        """d(dst)/d(src) by central differences; eps is in source units (pixels)."""
        p = np.atleast_2d(np.asarray(p, float))
        J = np.empty((len(p), 2, 2))
        for k in range(2):
            d = np.zeros(2)
            d[k] = eps
            J[:, :, k] = (self.predict(p + d) - self.predict(p - d)) / (2 * eps)
        return J


def fit(method, src, dst):
    if method not in MIN_POINTS:
        raise ValueError(f"unknown method {method}; use one of {sorted(MIN_POINTS)}")
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2:
        raise ValueError(f"src and dst must both be (N, 2), got {src.shape} and {dst.shape}")
    if not (np.isfinite(src).all() and np.isfinite(dst).all()):
        raise ValueError("non-finite control point")
    n = len(src)
    if n < MIN_POINTS[method]:
        raise ValueError(f"{method} needs at least {MIN_POINTS[method]} points, got {n}")
    Ts, Td = _norm(src), _norm(dst)
    s, d = _h(Ts, src), _h(Td, dst)
    if method == "projective":
        rows = []
        for (x, y), (u, v) in zip(s, d):
            rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
            rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
        M = np.array(rows)
        _, sv, Vt = np.linalg.svd(M)
        # an underdetermined system has a second (near) zero singular value
        if sv[7] < RCOND * 1e3 * sv[0]:
            raise ValueError("points do not determine a projective transform (collinear or degenerate)")
        Hn = Vt[-1].reshape(3, 3)
        if abs(Hn[2, 2]) < 1e-12:
            raise ValueError("degenerate projective transform")
        return Fit(method, Ts, Td, Hn / Hn[2, 2])
    F = _poly_features(s, DEGREE[method])
    sv = np.linalg.svd(F, compute_uv=False)
    if sv[-1] < 1e-6 * sv[0]:
        raise ValueError(f"points do not determine a {method} transform (collinear or degenerate)")
    params, *_ = np.linalg.lstsq(F, d, rcond=None)
    return Fit(method, Ts, Td, params)


def loo_residuals(method, src, dst):
    """Distance between each point and the prediction of a fit made without it."""
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    out = np.empty(len(src))
    for i in range(len(src)):
        keep = np.arange(len(src)) != i
        m = fit(method, src[keep], dst[keep])
        out[i] = np.hypot(*(m.predict(src[i:i + 1])[0] - dst[i]))
    return out
