# -*- coding: utf-8 -*-
import sys
"""Python probe: do the installed static linters share blind spots?

Builds a corpus of unambiguous defects (across several classes with hard ground
truth), runs the installed linters (pylint / ruff / flake8) against it,
builds a miss matrix, and measures miss correlation with the core — per EACH
class separately (no pooling). Additionally ranks redundancy: which check
can be removed from the stack without losing coverage.
"""
from . import corpus as _corpus
from . import linters as _linters
from . import core as _core


def build_miss_csv(out_path, linters=None, verbose=True):
    """Run all corpus classes through the linters, write a unified CSV. Returns (csv, used)."""
    used = linters or _linters.available_linters()
    if len(used) < 2:
        all_three = ["pylint", "ruff", "flake8"]
        miss = [n for n in all_three if not _linters.is_installed(n)]
        raise SystemExit(
            "At least 2 installed linters are required for the probe.\n"
            f"Currently available: {used or 'none'}.\n"
            f"Install the missing ones INTO THE SAME environment where blindspot is installed:\n"
            f"    {sys.executable} -m pip install {' '.join(miss or all_three)}\n"
            "Check: blindspot doctor")
    classes = _corpus.build_all_classes()
    header = ["task_id", "defect_class", "ground_truth_defect"] + [f"miss_{m}" for m in used]
    lines = [",".join(header)]
    n_total = 0
    for defect_class, snippets in classes:
        for tid, (src, has_defect) in snippets.items():
            n_total += 1
            row = [tid, defect_class, "1" if has_defect else "0"]
            for m in used:
                v = _linters.run_on_source(m, src, defect_class)
                row.append("" if v is None else str(v))
            lines.append(",".join(row))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if verbose:
        cls_names = ", ".join(c for c, _ in classes)
        print(f"Corpus: {n_total} snippets | classes: {cls_names} | linters: {', '.join(used)}")
    return out_path, used


def _redundancy_ranking(report):
    """Given the miss-correlation matrix for each Z, builds a recommendation:
    which linter is redundant (its misses are most strongly correlated with another,
    i.e. it adds almost no new coverage). Greedy: marks a candidate for
    removal if there is a pair with corr-CI strictly above the threshold."""
    print("\n" + "=" * 70)
    print("STACK COMPOSITION ADVICE (per defect class separately)")
    print("=" * 70)
    for z, data in report.items():
        res = data["res"]
        n = data["n"]
        pairs = res["pairwise"]
        print(f"\n-- class {z} (n={n}) --")
        # look for duplicates (lower CI bound is high) and independents
        dupes, weak, indep = [], [], []
        for pair, p in pairs.items():
            a, b = pair.split("|")
            lo = p["corr_ci"][0]
            corr = p["corr"]
            if lo != lo:  # nan
                continue
            if lo > 0.8:
                dupes.append((a, b, corr))
            elif lo > 0:
                weak.append((a, b, corr))
            else:
                indep.append((a, b, corr))
        for a, b, c in dupes:
            print(f"  • {a} ~ {b}: corr={c:+.2f} — DUPLICATES. "
                  f"One of the two can be removed from CI without losing coverage for {z}.")
        for a, b, c in weak:
            print(f"  • {a} ~ {b}: corr={c:+.2f} — partial overlap. "
                  f"They complement each other only partially; keeping both is barely justified.")
        for a, b, c in indep:
            print(f"  • {a} ~ {b}: corr={c:+.2f} — independent, they complement each other. "
                  f"Keeping both is useful.")
        if n < 10:
            print(f"  ! n<10 for class {z}: advice is a guideline, not a verdict.")


def run(out_csv="blindspot_misses.csv", n_boot=2000, seed=0, verbose=True):
    csv_path, used = build_miss_csv(out_csv, verbose=verbose)
    report = _core.analyze_csv(csv_path, n_boot=n_boot, seed=seed, verbose=verbose)
    if verbose:
        _redundancy_ranking(report)
        print(f"\nMiss matrix saved: {csv_path}")
    return report
