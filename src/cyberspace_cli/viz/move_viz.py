"""Terminal-based movement visualization for Cyberspace."""
from dataclasses import dataclass
from typing import Optional, List
import typer
import os

TERRAIN_COLORS = [
    "#0000ff", "#0044ff", "#0088ff", "#00ccff", "#00ffff",
    "#44ff44", "#88ff00", "#ccff00", "#ffff00", "#ffcc00",
    "#ff8800", "#ff4400", "#ff0000", "#ff0044", "#ff0088",
    "#ff00cc", "#ff00ff",
]


def terrain_color(terrain_k: int) -> str:
    if terrain_k < 0:
        terrain_k = 0
    if terrain_k > 16:
        terrain_k = 16
    return TERRAIN_COLORS[terrain_k]


def get_terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def run_move_viz(current_x: int, current_y: int, current_z: int, plane: int) -> None:
    try:
        from textual.app import App, ComposeResult
        from textual.widgets import Header, Footer, Static
        from textual.containers import Container
        from textual.binding import Binding
        from textual import events
    except ImportError as e:
        typer.echo("TUI visualizer dependencies not installed.", err=True)
        typer.echo("Install: pip install 'cyberspace-cli[viz]'", err=True)
        raise typer.Exit(code=1)
    
    from cyberspace_core.movement import preview_movement
    
    @dataclass
    class VizState:
        virtual_x: int = 0
        virtual_y: int = 0
        virtual_z: int = 0
        current_axis: str = 'x'
        committed: bool = False
    
    state = VizState()
    
    class MoveVizApp(App):
        CSS = """
        Screen { background: #000000; }
        
        #main-container { height: 100%; }
        #info-bar { height: 3; background: #1a1a2e; padding: 0 1; }
        
        #viz-row {
            height: 1fr;
            background: #000000;
        }
        
        #label-col {
            width: 11;
            height: 100%;
            padding: 0 1;
            color: #666666;
        }
        
        #data-col {
            height: 100%;
            background: #000000;
        }
        
        #data-panel {
            height: 4;
            background: #1a1a2e;
            padding: 0 1;
        }
        """
        
        BINDINGS = [
            Binding("x", "switch_axis('x')", "X"),
            Binding("y", "switch_axis('y')", "Y"),
            Binding("z", "switch_axis('z')", "Z"),
            Binding("left", "move_virtual(-1)", "←"),
            Binding("right", "move_virtual(1)", "→"),
            Binding("a", "move_virtual(-1)", "Left"),
            Binding("d", "move_virtual(1)", "Right"),
            Binding("h", "move_virtual(-1)", "Left"),
            Binding("l", "move_virtual(1)", "Right"),
            Binding("shift+left", "move_virtual(-10)", "←10"),
            Binding("shift+right", "move_virtual(10)", "→10"),
            Binding("ctrl+left", "move_virtual(-100)", "←100"),
            Binding("ctrl+right", "move_virtual(100)", "→100"),
            Binding("colon", "jump_offset", "Jump"),
            Binding("enter", "commit_movement", "Commit"),
            Binding("escape", "quit", "Cancel"),
        ]
        
        def __init__(self):
            super().__init__()
            self.info_bar = None
            self.label_col = None
            self.data_col = None
            self.data_panel = None
            self.span = 30
        
        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            with Container(id="main-container"):
                yield Static(id="info-bar")
                # Use a Static with markup for the two-column layout
                yield Static(id="viz-row")
                yield Static(id="data-panel")
            yield Footer()
        
        def on_mount(self) -> None:
            self.info_bar = self.query_one("#info-bar", Static)
            self.data_col = self.query_one("#viz-row", Static)
            self.data_panel = self.query_one("#data-panel", Static)
            self.recalculate_span()
            self.refresh_display()
        
        # Don't recalculate on resize - use fixed span
        # def on_resize(self, event: events.Resize) -> None:
        #     self.recalculate_span()
        #     self.refresh_display()
        
        def recalculate_span(self) -> None:
            width = get_terminal_width()
            self.span = max(5, min(100, (width - 14) // 2))
        
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
            """Open input modal to type offset."""
            self.push_screen(InputModal())
        
        def action_commit_movement(self) -> None:
            state.committed = True
            self.exit(return_code=0)
        
        def refresh_display(self) -> None:
            if not all([self.info_bar, self.data_col, self.data_panel]):
                return
            
            voff = (state.virtual_x if state.current_axis == 'x' else
                    state.virtual_y if state.current_axis == 'y' else state.virtual_z)
            
            axis_name, center_val, previews = preview_movement(
                current_x, current_y, current_z,
                state.virtual_x, state.virtual_y, state.virtual_z,
                state.current_axis, self.span, plane,
            )
            
            self.info_bar.update(
                f"[bold]{axis_name}[/] | Pos: [cyan]{center_val:,}[/] | "
                f"Offset: [yellow]{voff:+,}[/]"
            )
            
            # Build label and data columns separately, render as markup table
            # Using markup to position label column at start of each line
            data_rows = self._build_data_rows(previews, voff)
            
            # Labels - all exactly 10 chars
            label_list = [
                "Difficulty",
                " LCA (10s)",
                " LCA  (1s)",
                " △  (sign)",
                " △ (1000s)",
                " △  (100s)",
                " △   (10s)",
                " △    (1s)",
                "  Target  ",  # Same width, centered
            ]
            
            # Build combined output: label (dim) + │ separator + data
            # Add center column highlight background
            combined = []
            center_idx = self.span  # Center column index
            for label, data in zip(label_list, data_rows):
                # Pad data to exactly 2*span+1 characters
                padded_data = data[:2*self.span+1].ljust(2*self.span+1)
                # Insert center column highlight: split data at center, add background
                if len(padded_data) > center_idx:
                    data_before = padded_data[:center_idx]
                    data_at_center = padded_data[center_idx]
                    data_after = padded_data[center_idx+1:]
                    # Highlight the center column with dark gray background
                    padded_data = f"{data_before}[on #1a1a2e]{data_at_center}[/]{data_after}"
                # dim label │ highlighted data
                combined.append(f"[dim]{label:>10}[/dim][dim] │[/dim] {padded_data}")
            
            self.data_col.update("\n".join(combined))
            
            if previews:
                avg = sum(p.lca_height for p in previews) / len(previews)
                mx = max(p.lca_height for p in previews)
                mink = min(p.terrain_k for p in previews)
                maxk = max(p.terrain_k for p in previews)
                t = 0.1 * (2 ** (mx - 15)) if mx > 15 else 0.1
                ts = f"{t:.1f}ms" if t < 1000 else f"{t/1000:.1f}s"
                self.data_panel.update(
                    f"[cyan]{previews[0].offset:+,}[/] to [cyan]{previews[-1].offset:+,}[/] │ "
                    f"LCA: [yellow]{avg:.1f}[/] max [red]{mx}[/] │ "
                    f"Terrain: [blue]{mink}[/]→[red]{maxk}[/] │ Est: [green]{ts}[/]"
                )
        
        def _build_data_rows(self, previews, virtual_offset):
            """Build data rows. ○ = virtual target (center), ● = actual position.
            
            previews[span] = virtual position (screen center)
            previews[i].offset is from preview_movement = axis_value - current_actual
            
            Virtual target is at screen center (always previews[span]).
            Actual position offset from virtual = -virtual_offset.
            So actual is at preview index: span - virtual_offset
            """
            diff, lca10, lca01 = [], [], []
            sign, k, h, t, o, tgt = [], [], [], [], [], []
            
            # Actual position index in previews array
            actual_idx = (len(previews) // 2) - virtual_offset
            # Virtual target is always at center
            virtual_idx = len(previews) // 2
            
            for i, p in enumerate(previews):
                # offset_from_actual is what we stored in preview_movement
                offset_from_actual = p.offset
                
                diff.append(f"[{terrain_color(p.terrain_k)}]▨[/]")
                lca10.append(str(p.lca_height // 10))
                lca01.append(str(p.lca_height % 10))
                
                # Sign relative to actual position
                sign.append("±" if i == actual_idx else ("-" if i < actual_idx else "+"))
                
                # Delta magnitude from actual
                delta_from_actual = i - actual_idx
                abs_d = abs(delta_from_actual)
                k.append(str((abs_d//1000)%10) if abs_d>=1000 else " ")
                h.append(str((abs_d//100)%10) if abs_d>=100 else " ")
                t.append(str((abs_d//10)%10) if abs_d>=10 else " ")
                o.append(str(abs_d % 10))
                
                # Target markers
                is_virtual = (i == virtual_idx)
                is_actual = (i == actual_idx)
                
                if is_virtual and is_actual:
                    tgt.append("[bold]◎[/]")
                elif is_virtual:
                    tgt.append("○")
                elif is_actual:
                    tgt.append("[bold]●[/]")
                else:
                    tgt.append(" ")
            
            return [
                "".join(diff),
                "".join(lca10),
                "".join(lca01),
                "".join(sign),
                "".join(k),
                "".join(h),
                "".join(t),
                "".join(o),
                "".join(tgt),
            ]
    
    class InputModal(Static):
        """Modal for entering numeric offset."""
        
        BINDINGS = [
            Binding("enter", "submit", "OK"),
            Binding("escape", "dismiss", "Cancel"),
        ]
        
        def __init__(self):
            super().__init__()
            self.input_value = ""
        
        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Static(
                "Enter offset (e.g., 1000 or -500):\n" + \
                "Press Enter to confirm, Esc to cancel",
                classes="modal-label",
            )
            yield Footer()
        
        def on_key(self, event) -> None:
            # Handle numeric input
            if event.key.isdigit() or event.key in ('-', '+'):
                self.input_value += event.key
                self.update(f"Offset: {self.input_value}")
            elif event.key == "backspace":
                self.input_value = self.input_value[:-1]
                self.update(f"Offset: {self.input_value}")
            elif event.key == "enter":
                self.action_submit()
            elif event.key == "escape":
                self.action_dismiss()
        
        def action_submit(self) -> None:
            try:
                offset = int(self.input_value) if self.input_value else 0
                if state.current_axis == 'x':
                    state.virtual_x = offset
                elif state.current_axis == 'y':
                    state.virtual_y = offset
                else:
                    state.virtual_z = offset
            except ValueError:
                pass
            self.app.pop_screen()
        
        def action_dismiss(self) -> None:
            self.app.pop_screen()
    
    app = MoveVizApp()
    app.run()
    
    if state.committed:
        typer.echo(f"\n[bold]Committing:[/]\n  X: {state.virtual_x:+,}\n  Y: {state.virtual_y:+,}\n  Z: {state.virtual_z:+,}\n")
    else:
        typer.echo("Cancelled.")


def move_viz_command() -> None:
    from cyberspace_cli.state import load_state
    from cyberspace_core.coords import coord_to_xyz
    
    state = load_state()
    if not state:
        typer.echo("No state. Use `cyberspace spawn` first.", err=True)
        raise typer.Exit(code=1)
    
    coord_int = int.from_bytes(bytes.fromhex(state.coord_hex), "big")
    x, y, z, plane = coord_to_xyz(coord_int)
    run_move_viz(x, y, z, plane)
