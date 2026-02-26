"""Optional 3D visualizer for Cyberspace coordinates.

This subpackage is only used by the `cyberspace 3d` command.

It intentionally imports heavy GUI deps (tkinter/matplotlib/numpy) only when
invoked, so the rest of the CLI stays lightweight.
"""
