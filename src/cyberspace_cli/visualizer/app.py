from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from decimal import Decimal
from tkinter import ttk
from typing import Optional

import matplotlib

# TkAgg gives us an embedded window + copyable text in a minimal way.
matplotlib.use("TkAgg")

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from cyberspace_cli.parsing import normalize_hex_32
from cyberspace_core.coords import coord_to_xyz, gps_to_dataspace_coord
from cyberspace_core.sector import SECTOR_BITS_DEFAULT, coord_to_sector_id, coord_to_sector_local_centered

from .viz import Marker, SceneConfig, coord_to_dataspace_km, draw_scene, draw_sector_scene


@dataclass
class AppState:
    status: str = ""


class CyberspaceVisualizerApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        initial_current_coord_hex: Optional[str] = None,
        initial_spawn_coord_hex: Optional[str] = None,
        initial_scale: float = 0.5,
        initial_grid_lines: int = 4,
        mode: str = "dataspace",
        sector_bits: int = SECTOR_BITS_DEFAULT,
    ) -> None:
        self.root = root

        self.mode = (mode or "dataspace").strip().lower()
        if self.mode not in ("dataspace", "sector"):
            self.mode = "dataspace"
        self.sector_bits = int(sector_bits)

        title = "Cyberspace 3D" if self.mode == "dataspace" else "Cyberspace 3D (Sector)"
        root.title(title)
        root.geometry("1150x740")

        self.state = AppState()

        self.spawn_coord_hex = initial_spawn_coord_hex or ""
        self.current_coord_hex = initial_current_coord_hex or ""

        # --- Controls ---
        controls = ttk.Frame(root, padding=10)
        controls.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(controls, text="Cyberspace 3D", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")

        # Provided coords
        ttk.Label(controls, text="From CLI (optional)").pack(anchor="w", pady=(8, 0))
        self.show_spawn_var = tk.BooleanVar(value=bool(self.spawn_coord_hex))
        self.show_current_var = tk.BooleanVar(value=bool(self.current_coord_hex))
        ttk.Checkbutton(controls, text="Show spawn", variable=self.show_spawn_var).pack(anchor="w")
        ttk.Checkbutton(controls, text="Show current", variable=self.show_current_var).pack(anchor="w")

        self.spawn_text = tk.Text(controls, height=2, width=42, wrap="word")
        self.spawn_text.pack(fill=tk.X, pady=(4, 0))
        self.spawn_text.configure(state="disabled")

        self.current_text = tk.Text(controls, height=2, width=42, wrap="word")
        self.current_text.pack(fill=tk.X, pady=(4, 0))
        self.current_text.configure(state="disabled")

        ttk.Button(controls, text="Render spawn/current", command=self.on_render_spawn_current).pack(
            fill=tk.X, pady=(6, 0)
        )

        ttk.Separator(controls).pack(fill=tk.X, pady=10)

        ttk.Label(controls, text="GPS Input", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")

        # Major-city presets (mirrors GPS test vectors)
        self.city_presets = {
            "New York City": (40.7128, -74.0060),
            "San Francisco": (37.7749, -122.4194),
            "London": (51.5074, -0.1278),
            "Tokyo": (35.6895, 139.6917),
            "Sydney": (-33.8688, 151.2093),
            "Singapore": (1.3521, 103.8198),
            "Dubai": (25.2048, 55.2708),
            "Mumbai": (19.0760, 72.8777),
            # ASCII label to avoid any potential Tk font/locale weirdness.
            "Sao Paulo": (-23.5505, -46.6333),
            "Cape Town": (-33.9249, 18.4241),
        }

        self.city_var = tk.StringVar(value="Custom")
        ttk.Label(controls, text="City preset").pack(anchor="w", pady=(6, 0))
        self.city_combo = ttk.Combobox(
            controls,
            textvariable=self.city_var,
            state="readonly",
            values=["Custom", *self.city_presets.keys()],
        )
        self.city_combo.pack(fill=tk.X)
        self.city_combo.bind("<<ComboboxSelected>>", self.on_city_selected)

        self.lat_var = tk.StringVar(value="0")
        self.lon_var = tk.StringVar(value="0")
        self.alt_var = tk.StringVar(value="0")

        self.scale_var = tk.StringVar(value=str(initial_scale))
        self.grid_lines_var = tk.StringVar(value=str(initial_grid_lines))

        self._labeled_entry(controls, "Latitude (deg)", self.lat_var)
        self._labeled_entry(controls, "Longitude (deg)", self.lon_var)
        self._labeled_entry(controls, "Altitude (m) [optional]", self.alt_var)

        ttk.Separator(controls).pack(fill=tk.X, pady=10)

        ttk.Label(controls, text="Render Options", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        self._labeled_entry(controls, "Scale (e.g. 0.5)", self.scale_var)
        self._labeled_entry(controls, "Grid lines (e.g. 4)", self.grid_lines_var)

        self.show_midplane_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Show midplane", variable=self.show_midplane_var).pack(anchor="w", pady=(4, 0))

        ttk.Button(controls, text="Convert GPS + Render", command=self.on_render_gps).pack(fill=tk.X, pady=(10, 0))
        ttk.Button(controls, text="Reset view", command=self.on_reset_view).pack(fill=tk.X, pady=(6, 0))
        ttk.Button(controls, text="Rotate mode", command=self.on_rotate_mode).pack(fill=tk.X, pady=(6, 0))

        ttk.Separator(controls).pack(fill=tk.X, pady=10)

        ttk.Label(controls, text="Coordinate (256-bit hex)", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")

        self.coord_in_var = tk.StringVar(value=self.current_coord_hex or "")
        self._labeled_entry(controls, "coord (0x...)", self.coord_in_var)
        ttk.Button(controls, text="Render coord hex", command=self.on_render_coord_hex).pack(fill=tk.X, pady=(6, 0))

        self.coord_out_text = tk.Text(controls, height=4, width=42, wrap="word")
        self.coord_out_text.pack(fill=tk.X, pady=(6, 0))
        self.coord_out_text.configure(state="disabled")
        ttk.Button(controls, text="Copy to Clipboard", command=self.on_copy).pack(fill=tk.X, pady=(6, 0))

        self.status_var = tk.StringVar(
            value='Tip: drag rotates. If drag translates, toggle off toolbar Pan/Zoom (or click "Rotate mode").'
        )
        ttk.Label(controls, textvariable=self.status_var, foreground="#888").pack(anchor="w", pady=(10, 0))

        # --- Figure ---
        fig_frame = ttk.Frame(root, padding=10)
        fig_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.fig = Figure(figsize=(7.6, 6.2), dpi=100)
        self.ax = self.fig.add_subplot(111, projection="3d")

        self.canvas = FigureCanvasTkAgg(self.fig, master=fig_frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, fig_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.last_markers = []

        # Ensure the default interaction is rotate (no active toolbar tool)
        self._ensure_rotate_mode()

        self._update_cli_coord_texts()

        # initial scene
        self._render_scene(markers=[], sector_label="")

        # Auto-render if we were given coords from the CLI.
        if self.spawn_coord_hex or self.current_coord_hex:
            self.on_render_spawn_current()

    def _labeled_entry(self, parent: ttk.Frame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label).pack(anchor="w")
        ent = ttk.Entry(row, textvariable=var)
        ent.pack(fill=tk.X)

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _ensure_rotate_mode(self) -> None:
        """Disable toolbar zoom/pan so drag rotates (matplotlib 3D default)."""

        tb = getattr(self, "toolbar", None)
        if tb is None:
            return

        mode = getattr(tb, "mode", "")
        if mode == "pan/zoom":
            tb.pan()  # toggles off
        elif mode == "zoom rect":
            tb.zoom()  # toggles off

    def _get_scene_config(self) -> SceneConfig:
        try:
            scale = float(self.scale_var.get().strip())
        except ValueError:
            scale = 0.5

        try:
            grid_lines = int(self.grid_lines_var.get().strip())
        except ValueError:
            grid_lines = 4

        return SceneConfig(
            scale=scale,
            grid_lines=grid_lines,
            show_midplane=bool(self.show_midplane_var.get()),
        )

    def _render_scene(self, *, markers, sector_label: str = "") -> None:
        cfg = self._get_scene_config()
        if self.mode == "sector":
            draw_sector_scene(self.ax, cfg=cfg, markers=markers, sector_label=sector_label)
        else:
            draw_scene(self.ax, cfg=cfg, markers=markers)
        self.canvas.draw_idle()
        self.last_markers = markers

    def _update_text_widget(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _update_cli_coord_texts(self) -> None:
        spawn = self.spawn_coord_hex or "(none)"
        cur = self.current_coord_hex or "(none)"
        self._update_text_widget(self.spawn_text, spawn)
        self._update_text_widget(self.current_text, cur)

    def _parse_coord_hex_to_marker(self, coord_hex: str, *, color: str, label: str) -> Marker:
        h = normalize_hex_32(coord_hex)
        coord_int = int.from_bytes(bytes.fromhex(h), "big")
        _x, _y, _z, plane = coord_to_xyz(coord_int)

        if self.mode == "sector":
            _sid, _plane2, (lx, ly, lz) = coord_to_sector_local_centered(coord=coord_int, sector_bits=self.sector_bits)
            # Keep the Marker dataclass unchanged; in sector mode position is normalized scene units.
            return Marker(position_km=(lx, ly, lz), color=color, label=f"{label} (plane={plane})")

        pos_km = coord_to_dataspace_km(coord_int)
        return Marker(position_km=pos_km, color=color, label=f"{label} (plane={plane})")

    def on_city_selected(self, _evt=None) -> None:
        city = self.city_var.get().strip()
        if not city or city == "Custom":
            return

        def apply_city() -> None:
            try:
                if city not in self.city_presets:
                    return
                lat, lon = self.city_presets[city]
                self.lat_var.set(str(lat))
                self.lon_var.set(str(lon))
                self._set_status(f"Preset: {city}")
            except Exception as e:
                self._set_status(f"Error applying preset: {e}")

        self.root.after(0, apply_city)

    def on_render_spawn_current(self) -> None:
        markers = []
        errors = []

        sector_label = ""
        anchor_sid = None
        if self.mode == "sector":
            # Sector framing always uses the current coord if present (even if hidden),
            # falling back to spawn if that's all we have.
            anchor_hex = (self.current_coord_hex or "") or (self.spawn_coord_hex or "")
            if anchor_hex:
                try:
                    h = normalize_hex_32(anchor_hex)
                    coord_int = int.from_bytes(bytes.fromhex(h), "big")
                    anchor_sid, _plane = coord_to_sector_id(coord=coord_int, sector_bits=self.sector_bits)
                    sector_label = anchor_sid.tag()
                except Exception:
                    anchor_sid = None
                    sector_label = ""

        if self.show_spawn_var.get() and self.spawn_coord_hex:
            try:
                if self.mode == "sector" and anchor_sid is not None:
                    h = normalize_hex_32(self.spawn_coord_hex)
                    spawn_int = int.from_bytes(bytes.fromhex(h), "big")
                    spawn_sid, _plane = coord_to_sector_id(coord=spawn_int, sector_bits=self.sector_bits)
                    if spawn_sid != anchor_sid:
                        errors.append(f"spawn: different sector (S={spawn_sid.tag()})")
                    else:
                        markers.append(self._parse_coord_hex_to_marker(self.spawn_coord_hex, color="#00FF88", label="spawn"))
                else:
                    markers.append(self._parse_coord_hex_to_marker(self.spawn_coord_hex, color="#00FF88", label="spawn"))
            except Exception as e:
                errors.append(f"spawn: {e}")

        if self.show_current_var.get() and self.current_coord_hex:
            try:
                markers.append(self._parse_coord_hex_to_marker(self.current_coord_hex, color="#FF0000", label="current"))
            except Exception as e:
                errors.append(f"current: {e}")

        if not markers:
            msg = "No spawn/current coords to render."
            if errors:
                msg += " (" + "; ".join(errors) + ")"
            self._set_status(msg)
            self._render_scene(markers=[], sector_label=sector_label)
            return

        self._render_scene(markers=markers, sector_label=sector_label)
        if errors:
            self._set_status("Rendered with warnings: " + "; ".join(errors))
        else:
            self._set_status("Rendered spawn/current.")

    def on_render_gps(self) -> None:
        try:
            lat = self.lat_var.get().strip()
            lon = self.lon_var.get().strip()
            alt = self.alt_var.get().strip() or "0"

            # Treat alt=0 (including "0.0", "0e0", etc) as the default surface clamp.
            clamp_to_surface = False
            try:
                clamp_to_surface = Decimal(alt) == Decimal(0)
            except Exception:
                clamp_to_surface = True

            coord = gps_to_dataspace_coord(lat, lon, alt, clamp_to_surface=clamp_to_surface)
            coord_hex = "0x" + coord.to_bytes(32, "big").hex()

            self.current_coord_hex = coord_hex
            self.coord_in_var.set(coord_hex)
            self._update_cli_coord_texts()

            # Render with spawn (optional)
            self.on_render_spawn_current()
            self._update_text_widget(self.coord_out_text, coord_hex)

            self._set_status("Rendered GPS coordinate.")
        except Exception as e:
            self._set_status(f"Error: {e}")

    def on_render_coord_hex(self) -> None:
        try:
            coord_hex = self.coord_in_var.get().strip()
            if not coord_hex:
                self._set_status("Provide a coord hex first.")
                return

            # This becomes our "current".
            self.current_coord_hex = coord_hex
            self._update_cli_coord_texts()
            self.on_render_spawn_current()
            self._update_text_widget(self.coord_out_text, coord_hex)
            self._set_status("Rendered coord hex.")
        except Exception as e:
            self._set_status(f"Error: {e}")

    def on_reset_view(self) -> None:
        self._ensure_rotate_mode()

        sector_label = ""
        if self.mode == "sector":
            anchor_hex = (self.current_coord_hex or "") or (self.spawn_coord_hex or "")
            if anchor_hex:
                try:
                    h = normalize_hex_32(anchor_hex)
                    coord_int = int.from_bytes(bytes.fromhex(h), "big")
                    sid, _plane = coord_to_sector_id(coord=coord_int, sector_bits=self.sector_bits)
                    sector_label = sid.tag()
                except Exception:
                    sector_label = ""

        self._render_scene(markers=self.last_markers, sector_label=sector_label)
        self._set_status("View reset.")

    def on_rotate_mode(self) -> None:
        self._ensure_rotate_mode()
        self._set_status("Rotate mode (disabled pan/zoom tools).")

    def on_copy(self) -> None:
        value = self.coord_out_text.get("1.0", tk.END).strip()
        if not value:
            self._set_status("Nothing to copy yet.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self._set_status("Copied to clipboard.")


def run_app(
    *,
    current_coord_hex: Optional[str] = None,
    spawn_coord_hex: Optional[str] = None,
    scale: float = 0.5,
    grid_lines: int = 4,
    mode: str = "dataspace",
    sector_bits: int = SECTOR_BITS_DEFAULT,
) -> int:
    root = tk.Tk()
    _ = CyberspaceVisualizerApp(
        root,
        initial_current_coord_hex=current_coord_hex,
        initial_spawn_coord_hex=spawn_coord_hex,
        initial_scale=scale,
        initial_grid_lines=grid_lines,
        mode=mode,
        sector_bits=sector_bits,
    )
    root.mainloop()
    return 0


def main(argv: list[str]) -> int:
    # Minimal arg parser (keep this module importable without Typer).
    current = None
    spawn = None
    scale = 0.5
    grid = 4
    mode = "dataspace"

    it = iter(argv[1:])
    for a in it:
        if a == "--coord":
            current = next(it, None)
        elif a == "--spawn":
            spawn = next(it, None)
        elif a == "--scale":
            v = next(it, None)
            if v is not None:
                scale = float(v)
        elif a == "--grid":
            v = next(it, None)
            if v is not None:
                grid = int(v)
        elif a == "--sector":
            mode = "sector"

    return run_app(current_coord_hex=current, spawn_coord_hex=spawn, scale=scale, grid_lines=grid, mode=mode)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
