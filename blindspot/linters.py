# -*- coding: utf-8 -*-
"""Wrappers for static linters, parameterized by defect class.

Each wrapper returns, for a snippet: 1 = MISSED the defect (false negative),
0 = caught, None = the linter is unavailable/crashed. Linters are narrowed to
the rules of the specific defect class so that background noise (docstrings,
line length) is not counted as "caught."

IMPORTANT (cross-platform): linters are invoked as `python -m <module>`, NOT as
a bare binary. On Windows pylint/ruff/flake8 are installed as .cmd/.exe, which
subprocess without a shell does not find (FileNotFoundError). Running via
sys.executable -m works the same on Windows, Linux, and macOS.

Intentionally static linters only: the probe does not execute the code under check.

Rule sets by class (RULES[class][linter]):
  unused_import   — unused / dead imports
  unused_variable — assigned but unread local variables
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

# rules per defect class
RULES = {
    "unused_import": {
        "pylint": "unused-import,unused-wildcard-import,reimported",
        "ruff":   "F401,F403,F405,F811",
        "flake8": "F401,F403,F405,F811",
    },
    "unused_variable": {
        "pylint": "unused-variable",
        "ruff":   "F841",
        "flake8": "F841",
    },
}

# linter name -> importable module name (for `python -m <module>`)
MODULE = {"pylint": "pylint", "ruff": "ruff", "flake8": "flake8"}


def _run(args, timeout=120):
    """Run `python -m <args>` cross-platform."""
    return subprocess.run([sys.executable, "-m", *args],
                          capture_output=True, text=True, timeout=timeout)


def _pylint(path, rules):
    r = _run(["pylint", "--score=n", "-f", "json", "--disable=all",
              f"--enable={rules}", path])
    try:
        return 0 if len(json.loads(r.stdout or "[]")) > 0 else 1
    except json.JSONDecodeError:
        return None


def _ruff(path, rules):
    r = _run(["ruff", "check", "--select", rules, "--output-format", "json", path])
    try:
        return 0 if len(json.loads(r.stdout or "[]")) > 0 else 1
    except json.JSONDecodeError:
        return None


def _flake8(path, rules):
    r = _run(["flake8", "--select", rules, path])
    return 0 if r.stdout.strip() else 1


REGISTRY = {
    "pylint": _pylint,
    "ruff":   _ruff,
    "flake8": _flake8,
}


def is_installed(name):
    """Is the linter installed — checked by module importability (cross-platform)."""
    mod = MODULE.get(name)
    if mod is None:
        return False
    return importlib.util.find_spec(mod) is not None


def available_linters():
    """List of installed linters (by module importability, not by PATH)."""
    return [name for name in REGISTRY if is_installed(name)]


def missing_install_hint(names):
    """Friendly hint for installing missing linters."""
    miss = [n for n in names if not is_installed(n)]
    if not miss:
        return ""
    return (f"Not installed: {', '.join(miss)}. "
            f"Install them into the CURRENT environment: pip install {' '.join(miss)}")


def run_on_source(name, source, defect_class="unused_import"):
    """Run linter `name` on `source` text for class `defect_class`. Returns 1/0/None."""
    rules = RULES.get(defect_class, {}).get(name)
    if rules is None:
        return None
    if not is_installed(name):
        return None
    fn = REGISTRY[name]
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as tf:
        tf.write(source)
        path = tf.name
    try:
        return fn(path, rules)
    finally:
        os.unlink(path)
