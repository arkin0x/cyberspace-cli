from __future__ import annotations

from dataclasses import dataclass

from cyberspace_core.coords import AXIS_MAX
from cyberspace_core.movement import find_lca_height


@dataclass(frozen=True)
class StepResult:
    current: int
    target: int
    next: int
    lca_height: int


def choose_next_axis_value_toward(*, current: int, target: int, max_lca_height: int) -> StepResult:
    """Choose a next axis value that moves toward the target while respecting max_lca_height.

    Constraint interpretation:
    - LCA height h is `bit_length(current ^ next)`.
    - Requiring `h <= max_lca_height` means `current` and `next` must share all bits
      at positions >= max_lca_height.
    - Equivalently: `current >> max_lca_height == next >> max_lca_height`.

    So the next hop must stay inside the current aligned block of size 2^max_lca_height.

    Raises ValueError if no progress can be made under the bound.
    """
    if current == target:
        return StepResult(current=current, target=target, next=current, lca_height=0)

    if max_lca_height <= 0:
        raise ValueError("max_lca_height must be >= 1 to make progress")

    block_base = (current >> max_lca_height) << max_lca_height
    block_end = block_base + (1 << max_lca_height) - 1

    if target < block_base:
        nxt = block_base
    elif target > block_end:
        nxt = block_end
    else:
        nxt = target

    if nxt == current:
        raise ValueError(
            f"cannot progress from {current} toward {target} with max_lca_height={max_lca_height}"
        )

    if not (0 <= nxt <= AXIS_MAX):
        raise ValueError("next value out of axis range")

    h = find_lca_height(current, nxt)
    if h > max_lca_height:
        # Defensive: should not happen due to block math.
        raise ValueError(f"internal error: computed h={h} > max_lca_height={max_lca_height}")

    return StepResult(current=current, target=target, next=nxt, lca_height=h)


@dataclass(frozen=True)
class NextHop:
    x: StepResult
    y: StepResult
    z: StepResult


def choose_next_hop_xyz(*, x: int, y: int, z: int, tx: int, ty: int, tz: int, max_lca_height: int) -> NextHop:
    """Choose a 3D hop toward (tx,ty,tz) with per-axis max LCA height bounds."""
    return NextHop(
        x=choose_next_axis_value_toward(current=x, target=tx, max_lca_height=max_lca_height),
        y=choose_next_axis_value_toward(current=y, target=ty, max_lca_height=max_lca_height),
        z=choose_next_axis_value_toward(current=z, target=tz, max_lca_height=max_lca_height),
    )
