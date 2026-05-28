# -*- coding: utf-8 -*-
"""blindspot — measures whether validators share blind spots (miss correlation
within a single defect class). NOT an "AI reliability framework" — a narrow
measurement tool. See README: what the tool does and, crucially, what it does NOT do."""
from .core import analyze_csv, load_misses, run_selftest, analyze_class, verdict_for_class
from .probe import run as probe_python

__version__ = "0.1.0"
__all__ = ["analyze_csv", "load_misses", "run_selftest",
           "analyze_class", "verdict_for_class", "probe_python"]
