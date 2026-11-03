"""Web Mercator (EPSG:3857) arithmetic for XYZ tiles.

Global pixel coordinates at zoom z: x grows eastwards from the antimeridian, y grows southwards
from the northern edge (85.0511 deg), and the world is tile_size * 2**z pixels wide.
"""

import numpy as np

R = 6378137.0
ORIGIN = np.pi * R  # 20037508.342789244
MAX_LAT = 85.0511287798066


def world_px(z, tile_size=256):
    return tile_size * 2.0**z


def lonlat_to_global_px(lon, lat, z, tile_size=256):
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    if np.any(np.abs(lon) > 180.0) or np.any(np.abs(lat) > MAX_LAT):
        raise ValueError(f"outside Web Mercator: lon {lon}, lat {lat}")
    n = world_px(z, tile_size)
    x = (lon + 180.0) / 360.0 * n
    phi = np.radians(lat)
    y = (1.0 - np.log(np.tan(phi) + 1.0 / np.cos(phi)) / np.pi) / 2.0 * n
    return x, y


def global_px_to_lonlat(x, y, z, tile_size=256):
    n = world_px(z, tile_size)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lon = x / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y / n))))
    return lon, lat


def global_px_to_mercator(x, y, z, tile_size=256):
    res = 2.0 * ORIGIN / world_px(z, tile_size)
    return np.asarray(x, dtype=float) * res - ORIGIN, ORIGIN - np.asarray(y, dtype=float) * res


def mercator_to_global_px(mx, my, z, tile_size=256):
    res = 2.0 * ORIGIN / world_px(z, tile_size)
    return (np.asarray(mx, dtype=float) + ORIGIN) / res, (ORIGIN - np.asarray(my, dtype=float)) / res


def mercator_to_lonlat(mx, my):
    lon = np.degrees(np.asarray(mx, dtype=float) / R)
    lat = np.degrees(np.arctan(np.sinh(np.asarray(my, dtype=float) / R)))
    return lon, lat


def lonlat_to_mercator(lon, lat):
    x, y = lonlat_to_global_px(lon, lat, 0)
    return global_px_to_mercator(x, y, 0)


def ground_resolution(lat, z, tile_size=256):
    """Metres on the ground per global pixel at this latitude."""
    return 2.0 * ORIGIN / world_px(z, tile_size) * np.cos(np.radians(lat))
