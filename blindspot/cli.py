# -*- coding: utf-8 -*-
"""CLI: blindspot {selftest | report <csv> | probe-python}."""
import argparse
import sys

from . import core, probe
from . import linters as _linters


def _doctor():
    """Environment diagnostics: Python, encoding, linters. Returns exit code."""
    print("=" * 60)
    print("BLINDSPOT DOCTOR — environment check")
    print("=" * 60)
    print(f"Python:     {sys.version.split()[0]}  ({sys.executable})")
    enc = (sys.stdout.encoding or "").lower()
    print(f"Encoding:   stdout={sys.stdout.encoding}")
    if enc and "utf" not in enc:
        print("  ! WARNING (typically Windows): stdout is not UTF-8 — garbled output may occur.")
        print("    Fix: set PYTHONUTF8=1   (or chcp 65001) before running.")
    print("\nLinters (checked via `python -m`, not from PATH):")
    avail = []
    for name in ("pylint", "ruff", "flake8"):
        ok = _linters.is_installed(name)
        print(f"  [{'OK ' if ok else '   '}] {name}" + ("" if ok else "  — not installed"))
        if ok:
            avail.append(name)
    print("")
    if len(avail) >= 2:
        print(f"Ready: {len(avail)} linters available — you can run `blindspot probe-python`.")
        return 0
    miss = [n for n in ("pylint", "ruff", "flake8") if n not in avail]
    print(f"Need at least 2 linters, found {len(avail)}. Install into THE CURRENT environment:")
    print(f"    {sys.executable} -m pip install {' '.join(miss)}")
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="blindspot",
        description="Checks whether validators share blind spots (miss correlation per defect class).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("selftest", help="run core selftest (required before trusting results)")
    s.add_argument("--n-boot", type=int, default=2000)
    s.add_argument("--seed", type=int, default=0)

    r = sub.add_parser("report", help="report from a ready miss matrix (CSV)")
    r.add_argument("csv")
    r.add_argument("--n-boot", type=int, default=2000)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--alpha", type=float, default=0.05)
    r.add_argument("--skip-selftest", action="store_true",
                   help="NOT recommended: skip mandatory core check before report")

    p = sub.add_parser("probe-python",
                       help="build corpus, run installed linters, produce report")
    p.add_argument("--out", default="blindspot_misses.csv")
    p.add_argument("--n-boot", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)

    sub.add_parser("doctor", help="check environment: linters, Python, encoding")

    c = sub.add_parser("candidate",
                       help="evaluate a new candidate validator against an already accepted set")
    c.add_argument("csv", help="miss matrix containing columns for the candidate and accepted validators")
    c.add_argument("--candidate", required=True, help="name of the miss_<candidate> column without the prefix")
    c.add_argument("--accepted", required=True,
                   help="accepted set as comma-separated names, e.g.: pylint,ruff")
    c.add_argument("--n-boot", type=int, default=2000)
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--alpha", type=float, default=0.05)

    a = ap.parse_args(argv)
    if a.cmd == "doctor":
        sys.exit(_doctor())
    if a.cmd == "selftest":
        sys.exit(core.run_selftest(a.n_boot, a.seed))
    if a.cmd == "report":
        # GATE: core must not be trusted until selftest passes
        if not a.skip_selftest:
            print("Checking core (selftest) before report...")
            rc = core.run_selftest(a.n_boot, a.seed)
            if rc != 0:
                print("\nFAILURE: core selftest did not pass — report is not valid. "
                      "Fix the core/environment, or deliberately use --skip-selftest.")
                sys.exit(rc)
            print("selftest passed — computing report.\n")
        core.analyze_csv(a.csv, n_boot=a.n_boot, seed=a.seed, alpha=a.alpha)
    if a.cmd == "probe-python":
        probe.run(out_csv=a.out, n_boot=a.n_boot, seed=a.seed)
    if a.cmd == "candidate":
        sys.exit(_run_candidate(a))


def _run_candidate(a):
    """Incremental evaluation of a candidate against the accepted set per defect class."""
    accepted = [s.strip() for s in a.accepted.split(",") if s.strip()]
    rep = core.analyze_csv(a.csv, n_boot=a.n_boot, seed=a.seed,
                           alpha=a.alpha, verbose=False)
    any_class = False
    for z, data in rep.items():
        members = [m for m in accepted if m in data["methods"]]
        if a.candidate not in data["methods"] or not members:
            continue
        any_class = True
        ev = core.evaluate_candidate(data["res"], a.candidate, members, data["n"])
        core.print_candidate_eval(ev, z)
    if not any_class:
        print("Candidate or accepted validators not found in the matrix. "
              "Check the miss_* column names in the CSV.")
        return 1
    return 0


if __name__ == "__main__":
    main()
