"""Terminal-based movement visualization for Cyberspace.

Launch with: cyberspace move viz

Controls:
- x/y/z: Switch to that axis
- Left/Right (or a/d, h/l): Move virtually one Gibson
- Enter: Commit and execute the planned movement
- Escape: Cancel and exit
- :N: Type relative offset (e.g., :1000 or :-500)

Layout:
┌─────────────────────────────────────────────────────────────┐
│ X Axis │ Position: 12,847,392 │ Virtual offset: +15        │
├─────────────────────────────────────────────────────────────┤
│                  △difficulty │ ▨ ▨ ▨ ▨ ▨ ▨ ▨ ▨ ● ▨ ▨ ...  │
│    LCA Height              17│ 5  3  2  4  8 12 15  8  0 ...│
│       Delta             +15 │-7 -6 -5 -4 -3 -2 -1  0 +1 ...│
└─────────────────────────────────────────────────────────────┘
"""
from dataclasses import dataclass
from typing import Optional, List, Tuple
import typer

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


def format_lca_color(lca_height: int) -> str:
    """Format LCA height with appropriate color markup."""
    if lca_height > 20:
        return f"[red]{lca_height}[/red]"
    elif lca_height > 15:
        return f"[orange1]{lca_height}[/orange1]"
    elif lca_height > 10:
        return f"[yellow]{lca_height}[/yellow]"
    else:
        return str(lca_height)


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
    
    # Span: how many coordinates to show on each side of center
    SPAN = 30  # ~60 coords total + labels, fits 80-char terminal
    
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
            margin-bottom: 1;
        }
        
        #coords-display {
            height: 10;
            background: $surface;
            padding: 0 1;
        }
        
        #data-panel {
            height: 6;
            background: $primary-background;
            padding: 0 1;
            margin-top: 1;
        }
        
        .label-column {
            width: 20;
            color: $text-muted;
            text-align: right;
            padding-right: 1;
        }
        
        .center-label {
            text-style: bold;
            color: $secondary;
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
            Binding("colon", "enter_offset", "Jump"),
            Binding("enter", "commit_movement", "Commit"),
            Binding("escape", "quit", "Cancel"),
        ]
        
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.info_bar = None
            self.coords_display = None
            self.data_panel = None
        
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
            self.refresh_display()
        
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
        
        def action_enter_offset(self) -> None:
            # For now, just bump by 100 in the current direction
            # Full input modal would go here
            if state.current_axis == 'x':
                state.virtual_x += 100
            elif state.current_axis == 'y':
                state.virtual_y += 100
            else:
                state.virtual_z += 100
            self.refresh_display()
        
        def action_commit_movement(self) -> None:
            state.committed = True
            self.exit(return_code=0)
        
        def refresh_display(self) -> None:
            if not self.info_bar or not self.coords_display or not self.data_panel:
                return
            
            # Get preview data
            axis_name, center_val, previews = preview_movement(
                current_x=current_x,
                current_y=current_y,
                current_z=current_z,
                virtual_x=state.virtual_x,
                virtual_y=state.virtual_y,
                virtual_z=state.virtual_z,
                axis=state.current_axis,
                span=SPAN,
                plane=plane,
            )
            
            # Get current virtual offset for this axis
            if state.current_axis == 'x':
                virtual_offset = state.virtual_x
            elif state.current_axis == 'y':
                virtual_offset = state.virtual_y
            else:
                virtual_offset = state.virtual_z
            
            # Update info bar
            self.info_bar.update(
                f"[bold]{axis_name} Axis[/bold] | "
                f"Position: [cyan]{center_val:,}[/cyan] Gibson | "
                f"Virtual offset: [yellow]{virtual_offset:+,}[/yellow]"
            )
            
            # Build the display with label column
            # Row labels (right-aligned, 20 chars wide)
            label_difficulty = "Temporal Difficulty:"
            label_lca = "LCA Height:"
            label_delta = "Delta (Gibsons):"
            
            # Center marker row (shows which column is identity/current position)
            label_center = "[bold]▼[/bold]"
            
            # Build data rows
            difficulty_cells = []
            lca_cells = []
            delta_cells = []
            center_markers = []
            
            for preview in previews:
                is_center = (preview.offset == 0)
                
                # Difficulty: colored block character
                diff_char = "▨"
                diff_color = terrain_color(preview.terrain_k)
                difficulty_cells.append(f"[{diff_color}]{diff_char}[/]")
                
                # LCA height with color coding
                lca_cells.append(format_lca_color(preview.lca_height))
                
                # Delta (relative to CURRENT actual position, not virtual center)
                delta_str = self._format_delta(preview.offset)
                delta_cells.append(delta_str)
                
                # Center marker (only for virtual center, which is where we'd land)
                if is_center:
                    center_markers.append("[bold reverse]●[/]")
                else:
                    center_markers.append(" ")
            
            # Join cells with spacing
            difficulty_row = " ".join(difficulty_cells)
            lca_row = "  ".join(lca_cells)
            delta_row = " ".join(delta_cells)
            center_row = " ".join(center_markers)
            
            # Assemble the display
            self.coords_display.update(
                f"[dim]{label_difficulty:>20}[/dim] │ {difficulty_row}\n"
                f"[dim]{label_lca:>20}[/dim] │ {lca_row}\n"
                f"[dim]{label_delta:>20}[/dim] │ {delta_row}\n"
                f"[dim]{'Identity:':>20}[/dim] │ {center_row}"
            )
            
            # Update data panel with summary stats
            if previews:
                avg_lca = sum(p.lca_height for p in previews) / len(previews)
                max_lca = max(p.lca_height for p in previews)
                min_difficulty = min(p.terrain_k for p in previews)
                max_difficulty = max(p.terrain_k for p in previews)
                
                # Estimate compute time based on max LCA (rough benchmark)
                # Assuming ~0.1ms per Cantor pair at h=20
                base_time_ms = 0.1 * (2 ** (max_lca - 15)) if max_lca > 15 else 0.1
                time_estimate = f"{base_time_ms:.1f}ms" if base_time_ms < 1000 else f"{base_time_ms/1000:.1f}s"
                
                self.data_panel.update(
                    f"Range: [cyan]{previews[0].offset:+,}[/cyan] to [cyan]{previews[-1].offset:+,}[/cyan] Gibsons\n"
                    f"LCA: avg=[yellow]{avg_lca:.1f}[/yellow] max=[red]{max_lca}[/red] │ "
                    f"Terrain: [blue]{min_difficulty}[/blue] (easiest) → [red]{max_difficulty}[/red] (hardest)\n"
                    f"Est. compute time (max LCA={max_lca}): ~[green]{time_estimate}[/green]"
                )
        
        def _format_delta(self, offset: int) -> str:
            """Format the delta value for display."""
            if offset == 0:
                return "[bold reverse]  0  [/reverse]"
            elif abs(offset) < 1000:
                return f"{offset:+5d}"
            else:
                return f"{offset:+6,d}"
    
    class InputOffsetScreen(App):
        """Simple screen for entering offset."""
        def on_mount(self):
            self.push_screen("input_modal")
    
    # Create and run the app
    app = MoveVizApp()
    result = app.run()
    
    if state.committed:
        # Show what will be committed
        typer.echo(
            f"\n[bold]Committing movement:[/bold]\n"
            f"  X: {state.virtual_x:+,}\n"
            f"  Y: {state.virtual_y:+,}\n"
            f"  Z: {state.virtual_z:+,}\n"
            f"\nCalculating proof-of-work..."
        )
        # In production: execute the actual movement here via move_commands.py
    else:
        typer.echo("Movement cancelled.")


# Entry point for the CLI command
def move_viz_command() -> None:
    """Launch the terminal-based movement visualizer.
    
    This command opens an interactive TUI for planning and executing
    movements through Cyberspace. Visualize LCA heights, terrain difficulty,
    and coordinate costs before committing to the proof-of-work.
    """
    from cyberspace_cli.state import load_state
    from cyberspace_core.coords import coord_to_xyz
    
    # Load current state
    state = load_state()
    if not state:
        typer.echo("No state. Use `cyberspace spawn` first.", err=True)
        raise typer.Exit(code=1)
    
    # Parse current position
    coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x, y, z, plane = coord_to_xyz(coord_int)
    
    # Launch the visualizer
    run_move_viz(
        current_x=x,
        current_y=y,
        current_z=z,
        plane=plane,
        privkey_hex=state.privkey_hex,
    )
