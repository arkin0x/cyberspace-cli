"""Terminal-based movement visualization for Cyberspace.

Launch with: cyberspace move viz

Controls:
- x/y/z: Switch to that axis
- Left/Right (or a/d, h/l): Move virtually one Gibson
- Enter: Commit and execute the planned movement
- Escape: Cancel and exit
- :N: Jump by +100/-100 Gibsons

Layout (1 char per coordinate, data stacked vertically):
┌──────────────────────────────────────────────────┐
│ X Axis │ Position: ... │ Virtual offset: +15   │
├──────────────────────────────────────────────────┤
│Difficulty:│▨▨▨▨▨▨▨▨●▨▨▨▨▨▨▨▨│ (colored blocks)
│ LCA(10s): │0000000011111111│ (tens digit)
│  LCA(1s): │6665432101234567│ (ones digit)
│Δ (sign):  │-------+++------│ (+/- sign)
│Δ (1000s): │                │ (thousands)
│Δ (100s):  │                │ (hundreds)
│Δ (10s):   │                │ (tens)
│Δ (1s):    │0123456789012345│ (ones)
│ Target:   │        ○ ●     │ (○=current, ●=virtual)
├──────────────────────────────────────────────────┤
│ Range: -30 to +30 │ LCA: avg=5.2 max=7 │ ...   │
└──────────────────────────────────────────────────┘
"""
from dataclasses import dataclass
from typing import Optional, List
import typer
import os

# Heatmap colors for terrain_k (0=blue, 16=red)
TERRAIN_COLORS = [
    "#0000ff",  # 0 - deep blue
    "#0044ff",  # 1
    "#0088ff",  # 2
    "#00ccff",  # 3
    "#00ffff",  # 4 - cyan
    "#44ff44",  # 5 - green
    "#88ff00",  # 6
    "#ccff00",  # 7
    "#ffff00",  # 8 - yellow
    "#ffcc00",  # 9
    "#ff8800",  # 10 - orange
    "#ff4400",  # 11
    "#ff0000",  # 12 - red
    "#ff0044",  # 13
    "#ff0088",  # 14
    "#ff00cc",  # 15
    "#ff00ff",  # 16 - magenta
]


def terrain_color(terrain_k: int) -> str:
    """Get hex color for terrain_k value (0-16)."""
    if terrain_k < 0:
        terrain_k = 0
    if terrain_k > 16:
        terrain_k = 16
    return TERRAIN_COLORS[terrain_k]


def format_lca_tens(lca_height: int) -> str:
    """Get tens digit of LCA height."""
    return str(lca_height // 10)


def format_lca_ones(lca_height: int) -> str:
    """Get ones digit of LCA height."""
    return str(lca_height % 10)


def get_terminal_width() -> int:
    """Get current terminal width in columns."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80  # Default fallback


def run_move_viz(
    current_x: int,
    current_y: int,
    current_z: int,
    plane: int,
    privkey_hex: Optional[str] = None,
) -> None:
    """Run the movement visualization TUI.
    
    Parameters
    ----------
    current_x, current_y, current_z : current position (u85 values)
    plane : current plane (0 or 1)
    privkey_hex : private key for signing the move when committed
    """
    try:
        from textual.app import App, ComposeResult
        from textual.widgets import Header, Footer, Static
        from textual.containers import Container
        from textual.binding import Binding
        from textual import events
    except ImportError as e:
        typer.echo("TUI visualizer dependencies not installed.", err=True)
        typer.echo("Install: pip install 'cyberspace-cli[viz]'", err=True)
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    
    from cyberspace_core.movement import preview_movement, CoordPreview
    from cyberspace_core.coords import AXIS_MAX
    
    @dataclass
    class VizState:
        """Mutable state for the visualizer."""
        virtual_x: int = 0
        virtual_y: int = 0
        virtual_z: int = 0
        current_axis: str = 'x'
        committed: bool = False
    
    state = VizState()
    
    class MoveVizApp(App):
        """Main movement visualization application."""
        
        CSS = """
        Screen {
            background: $surface;
        }
        
        #main-container {
            height: 100%;
        }
        
        #info-bar {
            height: 3;
            background: $primary-background;
            padding: 0 1;
            margin-bottom: 0;
        }
        
        #coords-display {
            height: 1fr;
            background: $surface;
            padding: 0 0;
        }
        
        #data-panel {
            height: 5;
            background: $primary-background;
            padding: 0 1;
            margin-top: 0;
        }
        """
        
        BINDINGS = [
            Binding("x", "switch_axis('x')", "X Axis"),
            Binding("y", "switch_axis('y')", "Y Axis"),
            Binding("z", "switch_axis('z')", "Z Axis"),
            Binding("left", "move_virtual(-1)", "← Left"),
            Binding("right", "move_virtual(1)", "Right →"),
            Binding("a", "move_virtual(-1)", "Left"),
            Binding("d", "move_virtual(1)", "Right"),
            Binding("h", "move_virtual(-1)", "Left"),
            Binding("l", "move_virtual(1)", "Right"),
            Binding("colon", "jump_offset", "Jump"),
            Binding("enter", "commit_movement", "Commit"),
            Binding("escape", "quit", "Cancel"),
        ]
        
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.info_bar = None
            self.coords_display = None
            self.data_panel = None
            self.span = 30  # Default, recalculated on resize
        
        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            
            with Container(id="main-container"):
                yield Static("", id="info-bar")
                yield Static("", id="coords-display")
                yield Static("", id="data-panel")
            
            yield Footer()
        
        def on_mount(self) -> None:
            self.info_bar = self.query_one("#info-bar", Static)
            self.coords_display = self.query_one("#coords-display", Static)
            self.data_panel = self.query_one("#data-panel", Static)
            self.recalculate_span()
            self.refresh_display()
        
        def on_resize(self, event: events.Resize) -> None:
            """Recalculate span when terminal is resized."""
            self.recalculate_span()
            self.refresh_display()
        
        def recalculate_span(self) -> None:
            """Calculate span based on terminal width and label columns."""
            width = get_terminal_width()
            # Labels take ~14 chars (e.g., "Delta (1s):  │")
            # Leave 1 char margin on right
            label_width = 14
            available = width - label_width - 1
            self.span = max(5, min(100, available // 2))
        
        def action_switch_axis(self, axis: str) -> None:
            state.current_axis = axis
            self.refresh_display()
        
        def action_move_virtual(self, delta: int) -> None:
            if state.current_axis == 'x':
                state.virtual_x += delta
            elif state.current_axis == 'y':
                state.virtual_y += delta
            else:
                state.virtual_z += delta
            self.refresh_display()
        
        def action_jump_offset(self) -> None:
            """Jump by +100 or -100 based on current direction."""
            if state.current_axis == 'x':
                state.virtual_x += 100 if state.virtual_x >= 0 else -100
            elif state.current_axis == 'y':
                state.virtual_y += 100 if state.virtual_y >= 0 else -100
            else:
                state.virtual_z += 100 if state.virtual_z >= 0 else -100
            self.refresh_display()
        
        def action_commit_movement(self) -> None:
            state.committed = True
            self.exit(return_code=0)
        
        def refresh_display(self) -> None:
            if not self.info_bar or not self.coords_display or not self.data_panel:
                return
            
            # Get virtual offset for current axis
            if state.current_axis == 'x':
                virtual_offset = state.virtual_x
            elif state.current_axis == 'y':
                virtual_offset = state.virtual_y
            else:
                virtual_offset = state.virtual_z
            
            # Get preview data
            axis_name, center_val, previews = preview_movement(
                current_x=current_x,
                current_y=current_y,
                current_z=current_z,
                virtual_x=state.virtual_x,
                virtual_y=state.virtual_y,
                virtual_z=state.virtual_z,
                axis=state.current_axis,
                span=self.span,
                plane=plane,
            )
            
            # Update info bar
            self.info_bar.update(
                f"[bold]{axis_name} Axis[/bold] | "
                f"Position: [cyan]{center_val:,}[/cyan] Gibson | "
                f"Virtual offset: [yellow]{virtual_offset:+,}[/yellow]"
            )
            
            # Build rows - each coordinate is exactly 1 character column
            # Row labels (all exactly 15 chars including │)
            label_diff = " Difficulty:  │"
            label_lca10 = "   LCA (10s): │"
            label_lca01 = "   LCA  (1s): │"
            label_sign = "   △   (sign): │"  # △ instead of Δ (single byte)
            label_k    = "   △  (1000s): │"
            label_h    = "   △   (100s): │"
            label_t    = "   △    (10s): │"
            label_o    = "   △     (1s): │"
            label_target="    Target:   │"
            
            # Build data strings (no spaces between columns)
            diff_cells = []
            lca_tens_cells = []
            lca_ones_cells = []
            sign_cells = []
            k_cells = []  # thousands
            h_cells = []  # hundreds
            t_cells = []  # tens
            o_cells = []  # ones
            target_cells = []
            
            for preview in previews:
                # Actual position offset (relative to current actual, not virtual)
                actual_offset = preview.offset
                
                # Difficulty: colored block
                diff_char = "▨"
                diff_color = terrain_color(preview.terrain_k)
                diff_cells.append(f"[{diff_color}]{diff_char}[/]")
                
                # LCA height: split into tens and ones digits
                lca_tens_cells.append(format_lca_tens(preview.lca_height))
                lca_ones_cells.append(format_lca_ones(preview.lca_height))
                
                # Delta sign row
                if actual_offset < 0:
                    sign_cells.append("-")
                elif actual_offset > 0:
                    sign_cells.append("+")
                else:
                    sign_cells.append("±")
                
                # Delta magnitude digits (absolute value)
                abs_offset = abs(actual_offset)
                k_digit = (abs_offset // 1000) % 10 if abs_offset >= 1000 else " "
                h_digit = (abs_offset // 100) % 10 if abs_offset >= 100 else " "
                t_digit = (abs_offset // 10) % 10 if abs_offset >= 10 else " "
                o_digit = abs_offset % 10
                
                k_cells.append(str(k_digit) if k_digit != " " else " ")
                h_cells.append(str(h_digit) if h_digit != " " else " ")
                t_cells.append(str(t_digit) if t_digit != " " else " ")
                o_cells.append(str(o_digit))
                
                # Target markers
                # ○ = actual current position (offset 0 relative to actual)
                # ● = virtual target position (where we'd land if we commit)
                is_actual_current = (actual_offset == 0)
                is_virtual_target = (preview.offset == -virtual_offset)
                
                if is_actual_current and is_virtual_target:
                    target_cells.append("[bold]◎[/]")  # Both at same spot
                elif is_actual_current:
                    target_cells.append("○")
                elif is_virtual_target:
                    target_cells.append("[bold]●[/]")
                else:
                    target_cells.append(" ")
            
            # Join cells with NO spaces (1 char per coordinate)
            diff_row = "".join(diff_cells)
            lca10_row = "".join(lca_tens_cells)
            lca01_row = "".join(lca_ones_cells)
            sign_row = "".join(sign_cells)
            k_row = "".join(k_cells)
            h_row = "".join(h_cells)
            t_row = "".join(t_cells)
            o_row = "".join(o_cells)
            target_row = "".join(target_cells)
            
            # Assemble display
            self.coords_display.update(
                f"[dim]{label_diff}[/dim] {diff_row}\n"
                f"[dim]{label_lca10}[/dim] {lca10_row}\n"
                f"[dim]{label_lca01}[/dim] {lca01_row}\n"
                f"[dim]{label_sign}[/dim] {sign_row}\n"
                f"[dim]{label_k}[/dim] {k_row}\n"
                f"[dim]{label_h}[/dim] {h_row}\n"
                f"[dim]{label_t}[/dim] {t_row}\n"
                f"[dim]{label_o}[/dim] {o_row}\n"
                f"[dim]{label_target}[/dim] {target_row}"
            )
            
            # Update data panel
            if previews:
                avg_lca = sum(p.lca_height for p in previews) / len(previews)
                max_lca = max(p.lca_height for p in previews)
                min_difficulty = min(p.terrain_k for p in previews)
                max_difficulty = max(p.terrain_k for p in previews)
                
                # Estimate compute time
                base_time_ms = 0.1 * (2 ** (max_lca - 15)) if max_lca > 15 else 0.1
                time_estimate = f"{base_time_ms:.1f}ms" if base_time_ms < 1000 else f"{base_time_ms/1000:.1f}s"
                
                self.data_panel.update(
                    f"Range: [cyan]{previews[0].offset:+,}[/cyan] to [cyan]{previews[-1].offset:+,}[/cyan] │ "
                    f"LCA: avg=[yellow]{avg_lca:.1f}[/yellow] max=[red]{max_lca}[/red] │ "
                    f"Terrain: [blue]{min_difficulty}[/blue]→[red]{max_difficulty}[/red] │ "
                    f"Est: [green]{time_estimate}[/green]"
                )
    
    # Create and run the app
    app = MoveVizApp()
    result = app.run()
    
    if state.committed:
        typer.echo(
            f"\n[bold]Committing movement:[/bold]\n"
            f"  X: {state.virtual_x:+,}\n"
            f"  Y: {state.virtual_y:+,}\n"
            f"  Z: {state.virtual_z:+,}\n"
            f"\nCalculating proof-of-work..."
        )
    else:
        typer.echo("Movement cancelled.")


def move_viz_command() -> None:
    """Launch the terminal-based movement visualizer."""
    from cyberspace_cli.state import load_state
    from cyberspace_core.coords import coord_to_xyz
    
    state = load_state()
    if not state:
        typer.echo("No state. Use `cyberspace spawn` first.", err=True)
        raise typer.Exit(code=1)
    
    coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x, y, z, plane = coord_to_xyz(coord_int)
    
    run_move_viz(
        current_x=x,
        current_y=y,
        current_z=z,
        plane=plane,
        privkey_hex=state.privkey_hex,
    )
