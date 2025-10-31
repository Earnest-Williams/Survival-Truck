from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class Axial:
    q: int
    r: int


@dataclass(frozen=True, slots=True)
class Cube:
    x: int
    y: int
    z: int

    def __post_init__(self) -> None:
        if self.x + self.y + self.z != 0:
            raise ValueError("For cube coords, x + y + z must be 0")


class Layout(Enum):
    ODD_R = "odd_r"
    EVEN_R = "even_r"
    ODD_Q = "odd_q"
    EVEN_Q = "even_q"


@dataclass(frozen=True, slots=True)
class Offset:
    col: int  # q-like
    row: int  # r-like
    layout: Layout
