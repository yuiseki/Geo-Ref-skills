"""Where a named feature is, as points, lines and areas in projected metres (EPSG:3857), and how far a position
is from it.

A map prints a name on or beside its feature: a street's name along the street, a district's name somewhere
inside the district, a station's name next to its point. Measuring a printed name against the one point a
gazetteer returns (the middle of one street segment, a district's centroid) put names 80 to 290 px off on a
Nagoya map and misled the scale fit on London and Manhattan maps (2026-11-04). Distance to the whole feature is
the measure that matches how names are printed.
"""

import math


def _closest_on_segment(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return (ax + t * dx, ay + t * dy)


def _inside(p, ring):
    x, y = p
    inside = False
    n = len(ring)
    for i in range(n - 1):
        (x1, y1), (x2, y2) = ring[i], ring[i + 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _centroid_area(ring):
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if abs(a) < 1e-9:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys)), 0.0
    return (cx / (3 * a), cy / (3 * a)), abs(a) / 2


class Shapes:
    def __init__(self, points=(), lines=(), areas=()):
        self.points = [tuple(p) for p in points]
        self.lines = [[tuple(p) for p in line] for line in lines if len(line) >= 2]
        self.areas = [[tuple(p) for p in ring] for ring in areas if len(ring) >= 4]

    @classmethod
    def from_overpass(cls, elements, project):
        """Overpass `out geom` elements: nodes are points, closed ways are areas, other ways and the way members
        of relations are lines (multipolygon rings are not assembled; their outlines still count as lines)."""
        pts, lines, areas = [], [], []

        def coords(geom):
            return [project(g["lon"], g["lat"]) for g in geom if g]

        for e in elements:
            if e.get("type") == "node" and "lat" in e:
                pts.append(project(e["lon"], e["lat"]))
            elif e.get("type") == "way" and e.get("geometry"):
                c = coords(e["geometry"])
                (areas if len(c) >= 4 and c[0] == c[-1] else lines).append(c)
            elif e.get("type") == "relation":
                for m in e.get("members", []):
                    if m.get("type") == "way" and m.get("geometry"):
                        c = coords(m["geometry"])
                        (areas if len(c) >= 4 and c[0] == c[-1] else lines).append(c)
                    elif m.get("type") == "node" and "lat" in m:
                        pts.append(project(m["lon"], m["lat"]))
        return cls(pts, lines, areas)

    def empty(self):
        return not (self.points or self.lines or self.areas)

    CORE = 0.25

    def closest(self, p):
        """The nearest position on the feature. An area's name is placed near its middle by map renderers, so an
        area counts as a core disc around its centroid, of CORE times its equivalent radius; anywhere inside the
        area would let any name agree with a large area (random names with 4 km areas passed 71 % of the time,
        2026-11-04)."""
        best, bd = None, math.inf
        for ring in self.areas:
            c, area = _centroid_area(ring)
            r = self.CORE * math.sqrt(area / math.pi)
            d = math.dist(p, c)
            q = tuple(p) if d <= r else (c[0] + (p[0] - c[0]) * r / d, c[1] + (p[1] - c[1]) * r / d)
            dq = math.dist(p, q)
            if dq < bd:
                best, bd = q, dq
        for q in self.points:
            d = math.dist(p, q)
            if d < bd:
                best, bd = q, d
        for line in self.lines:
            for a, b in zip(line, line[1:]):
                q = _closest_on_segment(p, a, b)
                d = math.dist(p, q)
                if d < bd:
                    best, bd = q, d
        return best

    def distance(self, p):
        q = self.closest(p)
        return math.inf if q is None else math.dist(p, q)

    def sides(self):
        """Width and height of the feature's bounding box, in metres."""
        xs = [p[0] for p in self.points] + [q[0] for s in self.lines + self.areas for q in s]
        ys = [p[1] for p in self.points] + [q[1] for s in self.lines + self.areas for q in s]
        if not xs:
            return 0.0, 0.0
        return max(xs) - min(xs), max(ys) - min(ys)

    def extent(self):
        """Diagonal of the feature's bounding box, in metres."""
        xs = [p[0] for p in self.points] + [q[0] for s in self.lines + self.areas for q in s]
        ys = [p[1] for p in self.points] + [q[1] for s in self.lines + self.areas for q in s]
        if not xs:
            return 0.0
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys))
