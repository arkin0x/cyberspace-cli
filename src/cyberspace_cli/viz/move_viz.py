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
    from textual.screen import Screen
    
    @dataclass
    class VizState:
        virtual_x: int = 0
        virtual_y: int = 0
        virtual_z: int = 0
        current_axis: str = 'x'
        committed: bool = False
        escape_pressed: bool = False
        plane: int = 0
    
    state = VizState()
    
    class MoveVizApp(App):
        CSS = """
        Screen { 
            background: #000000;
        }
        
        #main-container {
            height: 100%;
            layout: vertical;
        }
        
        #info-bar { 
            height: 3; 
            background: #1a1a2e; 
            padding: 0 1;
        }
        
        #viz-container {
            height: 12;
            layout: horizontal;
        }
        
        #label-col {
            width: 13;
            height: 100%;
            color: #666666;
            text-align: right;
            background: #000000;
        }
        
        #data-col {
            height: 100%;
            background: #000000;
        }
        
        #data-panel {
            height: 4;
            background: #1a1a2e;
            padding: 0 1;
            border: solid #444466;
        }
        
        #summary-panel {
            height: 3;
            background: #0d0d1a;
            padding: 0 1;
            border: solid #444466;
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
            Binding("escape", "reset_or_quit", "Reset/Quit"),
            Binding("r", "reset_to_origin", "Reset"),
        ]
        
        def __init__(self):
            super().__init__()
            self.info_bar = None
            self.label_col = None
            self.data_col = None
            self.data_panel = None
            self.summary_panel = None
            self.span = 30
            self.modal_open = False
        
        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            with Container(id="main-container"):
                yield Static(id="info-bar")
                with Container(id="viz-container"):
                    yield Static(id="label-col")
                    yield Static(id="data-col")
                yield Static(id="data-panel")
                yield Static(id="summary-panel")
            yield Footer()
        
        def on_mount(self) -> None:
            self.info_bar = self.query_one("#info-bar", Static)
            self.label_col = self.query_one("#label-col", Static)
            self.data_col = self.query_one("#data-col", Static)
            self.data_panel = self.query_one("#data-panel", Static)
            self.summary_panel = self.query_one("#summary-panel", Static)
            self.recalculate_span()
            self.refresh_display()
        
        def recalculate_span(self) -> None:
            width = get_terminal_width()
            # Account for: 13 (label) + 2 (spacing) = 15 chars overhead
            available = width - 15
            self.span = max(5, min(100, available // 2 - 2))  # -2 for safety margin
        
        def action_switch_axis(self, axis: str) -> None:
            state.current_axis = axis
            state.escape_pressed = False  # Clear escape flag on axis switch
            self.refresh_display()
        
        def action_move_virtual(self, delta: int) -> None:
            if state.current_axis == 'x':
                state.virtual_x += delta
            elif state.current_axis == 'y':
                state.virtual_y += delta
            else:
                state.virtual_z += delta
            # Any movement clears the escape flag - must press ESC twice in a row to exit
            state.escape_pressed = False
            self.refresh_display()
        
        def action_jump_offset(self) -> None:
            """Open input screen to type offset."""
            # Prevent stacking modals
            if self.modal_open:
                return
            # Clear escape flag on any new input action
            state.escape_pressed = False
            self.modal_open = True
            self.push_screen(JumpInput())
        
        def on_screen_resume(self) -> None:
            # Called when returning from a pushed screen (like JumpInput)
            # Refresh display to show any offset changes from the modal
            self.modal_open = False
            self.refresh_display()
        
        def action_reset_to_origin(self) -> None:
            """Reset virtual position to origin."""
            state.virtual_x = 0
            state.virtual_y = 0
            state.virtual_z = 0
            state.escape_pressed = False
            self.refresh_display()
        
        def action_reset_or_quit(self) -> None:
            """First ESC resets, second ESC quits."""
            if state.escape_pressed:
                state.committed = False
                self.exit(return_code=1)
            else:
                state.virtual_x = 0
                state.virtual_y = 0
                state.virtual_z = 0
                state.escape_pressed = True
                self.refresh_display()
        
        def action_commit_movement(self) -> None:
            state.committed = True
            self.exit(return_code=0)
        
        def refresh_display(self) -> None:
            if not all([self.info_bar, self.label_col, self.data_col, self.data_panel, self.summary_panel]):
                return
            
            voff = (state.virtual_x if state.current_axis == 'x' else
                    state.virtual_y if state.current_axis == 'y' else state.virtual_z)
            
            axis_name, center_val, previews = preview_movement(
                current_x, current_y, current_z,
                state.virtual_x, state.virtual_y, state.virtual_z,
                state.current_axis, self.span, state.plane,
            )
            
            # Show reset warning if escape was pressed
            reset_status = "[red]Press ESC again to EXIT[/]" if state.escape_pressed else "Ready"
            self.info_bar.update(
                f"[bold]{axis_name}[/] | Pos: [cyan]{center_val:,}[/] | "
                f"Offset: [yellow]{voff:+,}[/] | {reset_status}"
            )
            
            # Build label and data columns separately
            data_rows = self._build_data_rows(previews, voff)
            
            # Labels - all exactly 12 chars, right aligned
            label_list = [
                "  △  (sign)",
                "  △ (1000s)",
                "  △  (100s)",
                "  △   (10s)",
                "  △    (1s)",
                "  LCA (10s)",
                "  LCA  (1s)",
                "   Target  ",
                " Terrain K ",
            ]
            
            # Render label column (plain text, right aligned)
            self.label_col.update("\n".join(label_list))
            
            # Render data column - reorder rows to match new label order
            # Delta rows first, then LCA rows, then Target, then Terrain K
            data_content = "\n".join([
                data_rows[2],  # △ (sign)
                data_rows[3],  # △ (1000s)
                data_rows[4],  # △ (100s)
                data_rows[5],  # △ (10s)
                data_rows[6],  # △ (1s)
                data_rows[0],  # LCA (10s)
                data_rows[1],  # LCA (1s)
                data_rows[7],  # Target
                data_rows[8],  # Terrain K
            ])
            self.data_col.update(data_content)
            
            if previews:
                # Find the virtual target preview (center of screen)
                target_preview = previews[len(previews) // 2]
                target_lca = target_preview.lca_height
                target_k = target_preview.terrain_k
                target_size = target_preview.subtree_size
                
                # Estimate time based on target's compute requirements
                # Simple model: 2^h operations at ~1M ops/sec
                if target_lca <= 15:
                    t_ms = 0.1 * (2 ** (target_lca - 10))
                else:
                    t_ms = 0.1 * (2 ** (target_lca - 15))
                
                # Format with appropriate time unit
                if t_ms < 1:
                    ts = f"{t_ms * 1000:.0f}μs"
                elif t_ms < 1000:
                    ts = f"{t_ms:.1f}ms"
                elif t_ms < 60000:
                    ts = f"{t_ms / 1000:.1f}s"
                elif t_ms < 3600000:
                    ts = f"{t_ms / 60000:.1f}m"
                elif t_ms < 86400000:
                    ts = f"{t_ms / 3600000:.1f}h"
                else:
                    ts = f"{t_ms / 86400000:.1f}d"
                
                self.data_panel.update(
                    f"Target: {target_preview.offset:+,} | "
                    f"LCA: {target_lca} | "
                    f"Subtree: 2^{target_lca} | "
                    f"Est: {ts}"
                )
            
            # Update summary panel with cumulative virtual movement
            self.summary_panel.update(
                f"X: [cyan]{state.virtual_x:+,}[/]  |  "
                f"Y: [cyan]{state.virtual_y:+,}[/]  |  "
                f"Z: [cyan]{state.virtual_z:+,}[/]"
            )
        
        def _build_data_rows(self, previews, virtual_offset):
            """Build data rows. O = virtual target (center), X = actual position.
            
            Terrain K row uses numeric values with colors. All other rows are plain text.
            LCA 10s row shows space when digit is 0.
            On Z axis, adds black sun (☣) marker at far right of Target row.
            """
            lca10, lca01 = [], []
            sign, k, h, t, o, tgt = [], [], [], [], [], []
            terrain_row = []
            
            # Actual position index in previews array
            actual_idx = (len(previews) // 2) - virtual_offset
            # Virtual target is always at center
            virtual_idx = len(previews) // 2
            # Center column index for highlighting
            center_idx = len(previews) // 2
            # Is Z axis? (for black sun marker)
            is_z_axis = (state.current_axis == 'z')
            
            for i, p in enumerate(previews):
                is_center = (i == center_idx)
                
                # LCA 10s: space if 0, otherwise the digit (must be 1 char to maintain alignment)
                tens = p.lca_height // 10
                lca10.append(" " if tens == 0 else str(tens))
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
                    tgt.append("◎")
                elif is_virtual:
                    tgt.append("○")
                elif is_actual:
                    tgt.append("●")
                else:
                    tgt.append(" ")
                
                # Terrain K: show the numeric value with color markup
                color = terrain_color(p.terrain_k)
                k_display = str(p.terrain_k) if p.terrain_k < 10 else str(p.terrain_k)[-1]
                terrain_row.append(f"[{color}]{k_display}[/{color}]")
            
            # On Z axis, append black sun marker after the target row
            # This adds one extra character at the far right end
            if is_z_axis:
                # The target row already has all coordinates; black sun goes at the end
                # We'll handle this separately - append to final joined string
                pass
            
            target_str = "".join(tgt)
            if is_z_axis:
                # Black sun marker - same character as actual position marker, in purple
                target_str += "[#8613d3]●[/]"
            
            return [
                "".join(lca10),
                "".join(lca01),
                "".join(sign),
                "".join(k),
                "".join(h),
                "".join(t),
                "".join(o),
                target_str,
                "".join(terrain_row),
            ]
    
    class JumpInput(Screen):
        """Screen for entering jump offset."""
        
        # Screen has its own Enter/Escape bindings - don't inherit parent's
        BINDINGS = [
            Binding("enter", "submit", "Submit offset"),
            Binding("escape", "dismiss", "Cancel"),
        ]
        
        CSS = """
        JumpInput {
            align: center middle;
            background: #000000aa;
        }
        #jump-container {
            width: 50;
            height: 10;
            background: #1a1a2e;
            border: solid #333366;
            padding: 1 2;
        }
        #jump-label {
            text-align: center;
            padding: 1 0;
        }
        #jump-input {
            width: 100%;
            margin: 1 0;
        }
        """
        
        def compose(self) -> ComposeResult:
            with Container(id="jump-container"):
                yield Static("Enter relative offset:", id="jump-label")
                yield Static("0", id="jump-value")
        
        def on_mount(self) -> None:
            self.value = ""
            self.query_one("#jump-value", Static).update("0")
            self.focus()  # Ensure screen has focus to capture key events
        
        def on_key(self, event: events.Key) -> None:
            # Only handle numeric input and backspace here
            # Enter/Escape are handled by BINDINGS actions
            if event.key.isdigit():
                self.value += event.key
                self.query_one("#jump-value", Static).update(self.value or "0")
                event.stop()
                event.prevent_default()
            elif event.key in ("hyphen", "minus", "_"):
                # Toggle sign - supports multiple keyboard layouts
                if self.value.startswith("-"):
                    self.value = self.value[1:]
                else:
                    self.value = "-" + self.value
                self.query_one("#jump-value", Static).update(self.value or "0")
                event.stop()
                event.prevent_default()
            elif event.key == "backspace":
                self.value = self.value[:-1]
                self.query_one("#jump-value", Static).update(self.value or "0")
                event.stop()
                event.prevent_default()
            # Don't stop enter/escape - let the action handlers deal with them
        
        def action_submit(self) -> None:
            try:
                offset = int(self.value) if self.value else 0
                # Offset is relative to current virtual position
                if state.current_axis == 'x':
                    state.virtual_x += offset
                elif state.current_axis == 'y':
                    state.virtual_y += offset
                else:
                    state.virtual_z += offset
            except ValueError:
                pass
            # Signal parent that modal is closing
            if hasattr(self.app, 'modal_open'):
                self.app.modal_open = False
            self.app.pop_screen()
            # Parent app will refresh automatically via on_screen_resume
        
        def action_dismiss(self) -> None:
            # Stop the escape key from propagating - we're just dismissing, not resetting
            # Signal parent that modal is closing
            if hasattr(self.app, 'modal_open'):
                self.app.modal_open = False
            self.app.pop_screen()
    
    app = MoveVizApp()
    app.run()
    
    if state.committed:
        typer.echo(f"\n[bold]Committing:[/]\n  X: {state.virtual_x:+,}\n  Y: {state.virtual_y:+,}\n  Z: {state.virtual_z:+,}\n")
    elif state.escape_pressed:
        typer.echo("Cancelled.")
    else:
        typer.echo("No changes.")


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
