"""Optional GUI visualizers for Cyberspace.

Used by:
- `cyberspace 3d`
- `cyberspace lcaplot`

This subpackage intentionally imports heavy GUI deps (tkinter/matplotlib/numpy)
only when invoked, so the rest of the CLI stays lightweight.
"""
