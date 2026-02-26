from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Optional

import matplotlib

# TkAgg gives us an embedded window + editable controls.
matplotlib.use("TkAgg")

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from cyberspace_cli.lcaplot import block_boundary_offsets, compute_adjacent_lca_heights


@dataclass
class AppState:
    status: str = ""


class LCAPlotApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        initial_axis: str = "x",
        initial_center: int = 0,
        initial_span: int = 256,
        initial_direction: int = 1,
        initial_max_lca_height: int = 17,
        current_x: Optional[int] = None,
        current_y: Optional[int] = None,
        current_z: Optional[int] = None,
    ) -> None:
        self.root = root
        root.title("Cyberspace LCA Plot")
        root.geometry("1150x740")

        self.state = AppState()

        # --- Controls ---
        controls = ttk.Frame(root, padding=10)
        controls.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(controls, text="Cyberspace LCA Plot", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(
            controls,
            text="Plots LCA height for adjacent hops (v -> v±1) around a center axis value.",
            foreground="#666",
            wraplength=320,
        ).pack(anchor="w", pady=(4, 0))

        self.current_xyz = {"x": current_x, "y": current_y, "z": current_z}

        # Axis
        ttk.Label(controls, text="Axis").pack(anchor="w", pady=(10, 0))
        self.axis_var = tk.StringVar(value=initial_axis.lower())
        self.axis_combo = ttk.Combobox(controls, textvariable=self.axis_var, state="readonly", values=["x", "y", "z"])
        self.axis_combo.pack(fill=tk.X)

        # Direction
        ttk.Label(controls, text="Direction").pack(anchor="w", pady=(10, 0))
        self.dir_var = tk.StringVar(value="+1" if initial_direction == 1 else "-1")
        self.dir_combo = ttk.Combobox(controls, textvariable=self.dir_var, state="readonly", values=["+1", "-1"])
        self.dir_combo.pack(fill=tk.X)

        # Params
        self.center_var = tk.StringVar(value=str(initial_center))
        self.span_var = tk.StringVar(value=str(initial_span))
        self.max_lca_var = tk.StringVar(value=str(initial_max_lca_height))
        self.show_boundaries_var = tk.BooleanVar(value=True)

        self._labeled_entry(controls, "Center (u85 int)", self.center_var)
        self._labeled_entry(controls, "Span (half-window)", self.span_var)
        self._labeled_entry(controls, "Reference max_lca_height (h)", self.max_lca_var)
        ttk.Checkbutton(
            controls,
            text="Show 2^h block boundaries (starts/ends)",
            variable=self.show_boundaries_var,
        ).pack(anchor="w", pady=(6, 0))

        btn_row = ttk.Frame(controls)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_row, text="Render", command=self.on_render).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(btn_row, text="Reset", command=self.on_reset).pack(side=tk.LEFT, padx=(6, 0))

        if any(v is not None for v in self.current_xyz.values()):
            ttk.Button(controls, text="Center on current axis", command=self.on_center_on_current).pack(
                fill=tk.X, pady=(8, 0)
            )

        self.status_var = tk.StringVar(value="Tip: use Render after editing center/span/h.")
        ttk.Label(controls, textvariable=self.status_var, foreground="#888", wraplength=320).pack(
            anchor="w", pady=(10, 0)
        )

        # --- Figure ---
        fig_frame = ttk.Frame(root, padding=10)
        fig_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.fig = Figure(figsize=(7.6, 6.2), dpi=100)
        self.ax = self.fig.add_subplot(111)

        self.canvas = FigureCanvasTkAgg(self.fig, master=fig_frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, fig_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)

        # Bind enter to render.
        root.bind("<Return>", lambda _evt: self.on_render())

        self.on_render()

    def _labeled_entry(self, parent: ttk.Frame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label).pack(anchor="w")
        ent = ttk.Entry(row, textvariable=var)
        ent.pack(fill=tk.X)

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _parse_int(self, s: str, *, name: str) -> int:
        try:
            return int(s.strip(), 0)
        except ValueError:
            raise ValueError(f"{name} must be an int")

    def _direction(self) -> int:
        d = self.dir_var.get().strip()
        return 1 if d == "+1" else -1

    def on_center_on_current(self) -> None:
        axis = self.axis_var.get().strip().lower() or "x"
        v = self.current_xyz.get(axis)
        if v is None:
            self._set_status("No current coordinate available from state.")
            return
        self.center_var.set(str(v))
        self.on_render()

    def on_reset(self) -> None:
        # Keep axis/direction, just reset view to something sensible.
        self.span_var.set("256")
        self.max_lca_var.set("17")
        self.on_render()

    def on_render(self) -> None:
        try:
            axis = self.axis_var.get().strip().lower() or "x"
            center = self._parse_int(self.center_var.get(), name="center")
            span = self._parse_int(self.span_var.get(), name="span")
            max_h = self._parse_int(self.max_lca_var.get(), name="max_lca_height")
            direction = self._direction()

            series = compute_adjacent_lca_heights(center=center, span=span, direction=direction)

            self.ax.clear()

            # Plot offsets (so gigantic axis values are readable).
            self.ax.plot(series.offsets, series.heights, linewidth=1.0)

            # Reference line
            if max_h >= 0:
                self.ax.axhline(max_h, color="#cc0000", linestyle="--", linewidth=1.0, alpha=0.8)

            # Block boundary markers for that same h.
            if self.show_boundaries_var.get() and max_h >= 0:
                starts, ends = block_boundary_offsets(
                    center=center, series_start=series.start, series_end=series.end, h=max_h
                )

                # Avoid drawing absurd numbers of lines (small h with big span).
                max_lines = 200
                total = len(starts) + len(ends)
                if total <= max_lines:
                    for o in starts:
                        self.ax.axvline(o, color="#008800", linewidth=0.8, alpha=0.25)
                    for o in ends:
                        self.ax.axvline(o, color="#880000", linewidth=0.8, alpha=0.25)
                else:
                    self._set_status(
                        f"Rendered (skipped {total} boundary lines; too many for h={max_h}, span={span})."
                    )

            self.ax.set_title(
                f"axis={axis}  center={center}  span={span}  dir={'+' if direction == 1 else '-'}1"
            )
            self.ax.set_xlabel("offset from center (v - center)")
            self.ax.set_ylabel("lca_height(v, v±1)")
            self.ax.grid(True, alpha=0.25)

            if series.heights:
                self.ax.set_ylim(0, max(series.heights) + 1)

            self.fig.tight_layout()
            self.canvas.draw_idle()

            # Update status last (so boundary message can override).
            if "Rendered (skipped" not in self.status_var.get():
                self._set_status(
                    f"Rendered {len(series.heights)} points from v={series.start}..{series.end}. "
                    "Green=start-of-block, red=end-of-block (for h)."
                )
        except Exception as e:
            self._set_status(f"Error: {e}")


def run_app(
    *,
    axis: str = "x",
    center: int = 0,
    span: int = 256,
    direction: int = 1,
    max_lca_height: int = 17,
    current_x: Optional[int] = None,
    current_y: Optional[int] = None,
    current_z: Optional[int] = None,
) -> int:
    root = tk.Tk()
    _ = LCAPlotApp(
        root,
        initial_axis=axis,
        initial_center=center,
        initial_span=span,
        initial_direction=direction,
        initial_max_lca_height=max_lca_height,
        current_x=current_x,
        current_y=current_y,
        current_z=current_z,
    )
    root.mainloop()
    return 0


def main(argv: list[str]) -> int:
    # Minimal arg parser (keep this module importable without Typer).
    axis = "x"
    center = 0
    span = 256
    direction = 1
    max_lca_height = 17

    it = iter(argv[1:])
    for a in it:
        if a == "--axis":
            axis = (next(it, "x") or "x")
        elif a == "--center":
            center = int(next(it, "0") or "0", 0)
        elif a == "--span":
            span = int(next(it, "256") or "256", 0)
        elif a == "--direction":
            direction = int(next(it, "1") or "1", 0)
        elif a == "--max-lca-height":
            max_lca_height = int(next(it, "17") or "17", 0)

    return run_app(axis=axis, center=center, span=span, direction=direction, max_lca_height=max_lca_height)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
