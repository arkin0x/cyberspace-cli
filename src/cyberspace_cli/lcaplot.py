from __future__ import annotations

from dataclasses import dataclass

from cyberspace_core.coords import AXIS_MAX
from cyberspace_core.movement import find_lca_height


@dataclass(frozen=True)
class LCAPlotSeries:
    center: int
    direction: int  # +1 or -1
    start: int
    end: int
    offsets: list[int]
    heights: list[int]


def compute_adjacent_lca_heights(*, center: int, span: int, direction: int) -> LCAPlotSeries:
    """Compute LCA heights for adjacent values around center.

    This is intended for visualizing where "expensive" boundaries occur for hops that
    increment or decrement an axis by 1.

    If direction=+1, computes h(v, v+1).
    If direction=-1, computes h(v, v-1).

    The plotted x axis is returned as offsets: (v - center).
    """

    if direction not in (-1, 1):
        raise ValueError("direction must be +1 or -1")
    if span < 0:
        raise ValueError("span must be >= 0")
    if not (0 <= center <= AXIS_MAX):
        raise ValueError(f"center must be within [0, {AXIS_MAX}]")

    # Pick a safe v range so (v + direction) stays inside the axis domain.
    raw_start = max(0, center - span)
    raw_end = min(AXIS_MAX, center + span)

    if direction == 1:
        start = raw_start
        end = min(raw_end, AXIS_MAX - 1)
    else:
        start = max(raw_start, 1)
        end = raw_end

    offsets: list[int] = []
    heights: list[int] = []

    for v in range(start, end + 1):
        offsets.append(v - center)
        heights.append(find_lca_height(v, v + direction))

    return LCAPlotSeries(
        center=center,
        direction=direction,
        start=start,
        end=end,
        offsets=offsets,
        heights=heights,
    )


def block_boundary_offsets(*, center: int, series_start: int, series_end: int, h: int) -> tuple[list[int], list[int]]:
    """Return offsets (relative to center) where 2^h blocks start/end.

    Starts are v % 2^h == 0.
    Ends are   v % 2^h == 2^h-1.
    """

    if h < 0:
        raise ValueError("h must be >= 0")
    if not (0 <= center <= AXIS_MAX):
        raise ValueError(f"center must be within [0, {AXIS_MAX}]")
    if series_start < 0 or series_end > AXIS_MAX or series_start > series_end:
        raise ValueError("invalid series range")

    if h == 0:
        # Block size 1: every point is both a start and an end.
        starts = [v - center for v in range(series_start, series_end + 1)]
        ends = starts[:]
        return starts, ends

    block_size = 1 << h
    mask = block_size - 1

    starts: list[int] = []
    ends: list[int] = []

    for v in range(series_start, series_end + 1):
        low = v & mask
        if low == 0:
            starts.append(v - center)
        elif low == mask:
            ends.append(v - center)

    return starts, ends
