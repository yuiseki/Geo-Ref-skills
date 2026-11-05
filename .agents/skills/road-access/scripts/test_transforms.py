# uvx --with numpy --with scikit-image --with pytest pytest scripts/test_transforms.py
import numpy as np
import pytest
from skimage.transform import ProjectiveTransform

import transforms as tf

rng = np.random.default_rng(42)
# image pixels to EPSG:3857 metres near Tokyo, about 2.4 m per pixel, y flipped
A = np.array([[2.4, 0.3, 15556000.0], [0.2, -2.4, 4257000.0]])


def pts(n=30, w=1000, h=800):
    return np.column_stack([rng.uniform(0, w, n), rng.uniform(0, h, n)])


def apply_affine(p):
    return p @ A[:, :2].T + A[:, 2]


H = np.array([[2.4, 0.3, 15556000.0], [0.2, -2.4, 4257000.0], [2e-6, -1e-6, 1.0]])


def apply_h(p):
    q = np.column_stack([p, np.ones(len(p))]) @ H.T
    return q[:, :2] / q[:, 2:]


@pytest.mark.parametrize("method", ["affine", "projective", "poly2", "poly3"])
def test_recovers_an_affine_exactly(method):
    src = pts()
    m = tf.fit(method, src, apply_affine(src))
    test = pts(50)
    np.testing.assert_allclose(m.predict(test), apply_affine(test), atol=1e-4)


def test_projective_recovers_a_homography_and_affine_does_not():
    src = pts()
    dst = apply_h(src)
    test = pts(50)
    np.testing.assert_allclose(tf.fit("projective", src, dst).predict(test), apply_h(test), atol=1e-3)
    err = np.abs(tf.fit("affine", src, dst).predict(test) - apply_h(test)).max()
    assert err > 1.0


def test_projective_matches_scikit_image():
    src = pts(12)
    dst = apply_h(src) + rng.normal(0, 0.5, (12, 2))
    sk = ProjectiveTransform.from_estimate(src, dst)
    assert sk
    test = pts(5)
    ours = tf.fit("projective", src, dst).predict(test)
    np.testing.assert_allclose(ours, sk(test), atol=0.05)


def test_poly2_recovers_quadratic():
    src = pts(40)
    x, y = src[:, 0] / 1000, src[:, 1] / 1000
    dst = np.column_stack([3 + x + 0.2 * x * x - 0.1 * x * y, 5 - y + 0.05 * y * y])
    test = pts(20)
    tx, ty = test[:, 0] / 1000, test[:, 1] / 1000
    want = np.column_stack([3 + tx + 0.2 * tx * tx - 0.1 * tx * ty, 5 - ty + 0.05 * ty * ty])
    np.testing.assert_allclose(tf.fit("poly2", src, dst).predict(test), want, atol=1e-8)


@pytest.mark.parametrize("method,n", [("affine", 2), ("projective", 3), ("poly2", 5), ("poly3", 9)])
def test_too_few_points_is_an_error(method, n):
    src = pts(n)
    with pytest.raises(ValueError):
        tf.fit(method, src, apply_affine(src))


def test_collinear_points_are_an_error():
    t = rng.uniform(0, 1000, 20)
    src = np.column_stack([t, 0.5 * t + 3])
    for method in ["affine", "projective", "poly2"]:
        with pytest.raises(ValueError):
            tf.fit(method, src, apply_affine(src))


def test_loo_points_at_the_outlier():
    src = pts(20)
    dst = apply_affine(src) + rng.normal(0, 0.3, (20, 2))
    dst[7] += [60.0, -40.0]
    r = tf.loo_residuals("affine", src, dst)
    assert int(np.argmax(r)) == 7
    assert r[7] > 50
    # the outlier also pulls the fits that keep it, so the other residuals rise too (median about 6 here)
    assert r[7] > 5 * np.median(r)


def test_loo_is_larger_than_fit_residual():
    src = pts(12)
    dst = apply_affine(src) + rng.normal(0, 1.0, (12, 2))
    m = tf.fit("poly3", src, dst)
    fit_r = np.hypot(*(m.predict(src) - dst).T)
    loo = tf.loo_residuals("poly3", src, dst)
    assert loo.max() > fit_r.max()


def test_jacobian_of_affine():
    src = pts()
    m = tf.fit("affine", src, apply_affine(src))
    J = m.jacobian(np.array([[500.0, 400.0]]))[0]
    np.testing.assert_allclose(J, A[:, :2], atol=1e-5)
