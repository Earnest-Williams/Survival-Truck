from __future__ import annotations
from dataclasses import dataclass
from math import sqrt

@dataclass(frozen=True)
class Orientation:
    f0: float; f1: float; f2: float; f3: float
    b0: float; b1: float; b2: float; b3: float
    start_angle: float  # turns (0..1)


POINTY = Orientation(
    f0=sqrt(3.0),
    f1=sqrt(3.0) / 2.0,
    f2=0.0,
    f3=1.5,
    b0=sqrt(3.0) / 3.0,
    b1=-1.0 / 3.0,
    b2=0.0,
    b3=2.0 / 3.0,
    start_angle=0.5,
)
FLAT = Orientation(
    f0=1.5,
    f1=0.0,
    f2=sqrt(3.0) / 2.0,
    f3=sqrt(3.0),
    b0=2.0 / 3.0,
    b1=0.0,
    b2=-1.0 / 3.0,
    b3=sqrt(3.0) / 3.0,
    start_angle=0.0,
)

@dataclass
class Layout:
    orientation: Orientation
    size_x: float  # half-width for flat-top; ≈ W/√3 for pointy-top (see notes)
    size_y: float  # half-height for pointy-top; ≈ H/√3 for flat-top
    origin_x: float = 0.0
    origin_y: float = 0.0

    def hex_to_pixel(self, q: float, r: float) -> tuple[float, float]:
        M = self.orientation
        x = (M.f0 * q + M.f1 * r) * self.size_x + self.origin_x
        y = (M.f2 * q + M.f3 * r) * self.size_y + self.origin_y
        return x, y

    def pixel_to_hex_fractional(self, x: float, y: float) -> tuple[float, float, float]:
        M = self.orientation
        px = (x - self.origin_x) / self.size_x
        py = (y - self.origin_y) / self.size_y
        q = M.b0 * px + M.b1 * py
        r = M.b2 * px + M.b3 * py
        s = -q - r
        return q, r, s

def cube_round(qf: float, rf: float, sf: float) -> tuple[int, int, int]:
    qi, ri, si = round(qf), round(rf), round(sf)
    dq, dr, ds = abs(qi - qf), abs(ri - rf), abs(si - sf)
    if dq > dr and dq > ds:
        qi = -ri - si
    elif dr > ds:
        ri = -qi - si
    else:
        si = -qi - ri
    return qi, ri, si
