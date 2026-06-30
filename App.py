"""
App.py
─────────────────────────────────────────────────────────────────────────────
Compatibility entrypoint.

The original project structure shipped both `app.py` and `App.py`. This file
is kept so any existing deployment configuration that references `App:app`
continues to work unchanged. All real logic now lives in app.py — this file
simply re-exports the same Flask application instance.
─────────────────────────────────────────────────────────────────────────────
"""

from app import app  # noqa: F401
