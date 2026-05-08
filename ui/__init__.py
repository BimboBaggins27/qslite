"""ui/ package — per-tab render functions, extracted from app.py.

Each module exposes a `render(ss)` function called from app.py inside its
respective tab context. Goal: keep app.py as a thin shell (page config, CSS,
state init, sidebar, tab dispatch) and let each tab evolve independently.

Migration is incremental — simplest tabs first (audit, rate review).
"""
