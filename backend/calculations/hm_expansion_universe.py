"""Nifty 500 / Nifty 50 universe loading for the H-M expansion scanner.

Re-exports backend.calculations.universe — this module used to hold its own
near-verbatim copy of app/pages/12_🔭_HM_Scanner.py::_load_symbols(); both
now share one implementation. Kept as a thin re-export (not deleted) so
existing callers of this module's load_symbols/FALLBACK_NIFTY50 don't need
to change their imports.
"""
from __future__ import annotations

from backend.calculations.universe import FALLBACK_NIFTY50, load_symbols

__all__ = ["FALLBACK_NIFTY50", "load_symbols"]
