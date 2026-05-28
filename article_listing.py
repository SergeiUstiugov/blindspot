# -*- coding: utf-8 -*-
"""
Article listing for "Reliability of the generator + checks pairing".

Self-contained, depends only on numpy. Contains THREE blocks — it is important
not to confuse their purpose:

  1. METRIC + SELFTEST — working code of the miss-independence meter and
     its verification on synthetic data (the tool must distinguish an independent
     pair from a dependent one). This is what you can copy for yourself.

  2. ARITHMETIC RECONSTRUCTION — recomputing the metric on matrices ASSEMBLED
     FROM ALREADY-KNOWN coverage cells. This is an arithmetic check (the metric
     on a known input gives a known output), NOT obtaining a result.
     The numbers here are "baked in" by construction — this block cannot return
     a different answer, so it proves nothing about the linters themselves.
     See the warning.

  3. HOW TO GET THE REAL NUMBERS — this is not done by this file but by running
     the actual linters: `blindspot probe-python` (in the blindspot package).

Run:  python article_listing.py
"""
import numpy as np


# ════════════════════════════════════════════════════════════════════════════
# BLOCK 1. METRIC + SELFTEST  (working code, copy for yourself)
# ════════════════════════════════════════════════════════════════════════════

def independence_report(miss, n_boot=500, seed=0):
    """miss: (n, 2) binary miss matrix of two tools IN ONE defect class
    (1 = tool missed a real defect).
    Returns (phi, ratio, shuffle_null):
      phi   — φ miss-correlation (≈0 under independence);
      ratio — joint / product: how many times more often the joint miss occurs than
              under independence (≈1 under independence, >1 with a shared blind spot);
      null  — shuffle control: the φ level with the relationship destroyed (floor estimate)."""
    rng = np.random.default_rng(seed)
    a, b = miss[:, 0], miss[:, 1]
    phi = np.corrcoef(a, b)[0, 1] if a.std() and b.std() else np.nan
    joint = float(np.mean(a & b))
    prod = float(a.mean() * b.mean())
    ratio = joint / prod if prod > 0 else np.nan
    null = float(np.mean([
        np.corrcoef(a, rng.permutation(b))[0, 1] if a.std() and b.std() else 0.0
        for _ in range(n_boot)]))
    return phi, ratio, null


def bootstrap_ci(miss, fn, n_boot=1000, seed=1, alpha=0.05):
    """Percentile confidence interval of statistic fn(miss) via row resampling."""
    rng = np.random.default_rng(seed)
    n = len(miss)
    vals = []
    for _ in range(n_boot):
        v = fn(miss[rng.integers(0, n, n)])
        if v == v:  # not nan
            vals.append(v)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def _phi(miss):
    a, b = miss[:, 0], miss[:, 1]
    return np.corrcoef(a, b)[0, 1] if a.std() and b.std() else np.nan


def _ratio(miss):
    a, b = miss[:, 0], miss[:, 1]
    joint = float(np.mean(a & b))
    prod = float(a.mean() * b.mean())
    return joint / prod if prod > 0 else np.nan


def verdict(miss):
    """Verdict for the pair: independent only if BOTH CIs cover the neutral value
    (φ-CI covers 0 AND ratio-CI covers 1). Otherwise — dependent / inconclusive."""
    phi, ratio, _ = independence_report(miss)
    phi_ci = bootstrap_ci(miss, _phi)
    ratio_ci = bootstrap_ci(miss, _ratio)
    indep = (phi_ci[0] <= 0 <= phi_ci[1]) and (ratio_ci[0] <= 1 <= ratio_ci[1])
    return indep, phi, phi_ci, ratio, ratio_ci


def _show(label, miss):
    n = len(miss)
    indep, phi, phi_ci, ratio, ratio_ci = verdict(miss)
    tag = "INDEPENDENT" if indep else "DEPENDENT"
    if n < 10:
        tag += " / INCONCLUSIVE (n too small)"
    print(f"\n-- {label}  (n={n}) " + "-" * 36)
    print(f"  phi-corr = {phi:+.3f}  CI [{phi_ci[0]:+.3f}, {phi_ci[1]:+.3f}]")
    print(f"  ratio    = {ratio:.2f}  CI [{ratio_ci[0]:.2f}, {ratio_ci[1]:.2f}]")
    print(f"  marginal: A={miss[:,0].mean():.2f}  B={miss[:,1].mean():.2f}")
    print(f"  VERDICT: {tag}")
    return indep


def selftest():
    """The tool must both pass and fail: call an independent pair independent
    and a dependent pair dependent. Otherwise it cannot be trusted."""
    print("=" * 60)
    print("BLOCK 1. SELFTEST  (working meter on synthetic data)")
    print("=" * 60)
    rng = np.random.default_rng(0)
    n = 120
    # A — deliberately independent misses
    A = np.column_stack([rng.random(n) < 0.3, rng.random(n) < 0.4]).astype(int)
    a_ok = _show("A: deliberately INDEPENDENT (expected: independent)", A)
    # B — shared latent factor 'hard defect': they sometimes miss together
    hard = rng.random(n) < 0.35
    B = np.column_stack([rng.random(n) < 0.15, rng.random(n) < 0.15]).astype(int)
    B[hard, :] = 1
    b_ok = _show("B: deliberately DEPENDENT (expected: dependent)", B)
    ok = a_ok and not b_ok
    print(f"\n  SELFTEST {'PASSED' if ok else 'FAILED'}: "
          f"{'the tool distinguishes both cases' if ok else 'do NOT trust'}")
    return ok


# ════════════════════════════════════════════════════════════════════════════
# BLOCK 2. ARITHMETIC RECONSTRUCTION  (NOT obtaining a result!)
# ════════════════════════════════════════════════════════════════════════════

def reconstruction():
    """
    ⚠️ WARNING. The matrices below are assembled FROM ALREADY-KNOWN coverage cells
    (how many snippets both caught / only one / both missed). This is a check that
    the metric on a known input gives the expected output — and nothing more. The
    numbers here are "baked in" by construction: this block CANNOT return a different
    answer, so it PROVES NOTHING about the linters themselves. The real numbers come
    from actual runs (Block 3).
    """
    print("\n" + "=" * 60)
    print("BLOCK 2. ARITHMETIC RECONSTRUCTION  (NOT a proof!)")
    print("=" * 60)
    print("  Matrices assembled from known coverage cells — an arithmetic check,")
    print("  not a measurement. Real numbers are in Block 3 (running the linters).")

    # Coverage cells for the overlapping pylint × ruff pair (n=88), obtained
    # from a real run in the study: both catch 16 / only pylint 8 /
    # only ruff 24 / both missed 40.
    M = np.array([[0, 0]] * 16 + [[0, 1]] * 8 + [[1, 0]] * 24 + [[1, 1]] * 40,
                 dtype=int)
    _show("Reconstruction: pylint x ruff from cells 16/8/24/40", M)
    print("  (expected phi≈+0.26, ratio≈1.15 — arithmetic checks out)")


# ════════════════════════════════════════════════════════════════════════════
# BLOCK 3. HOW TO GET THE REAL NUMBERS  (not done by this file)
# ════════════════════════════════════════════════════════════════════════════

def how_to_get_real_numbers():
    print("\n" + "=" * 60)
    print("BLOCK 3. HOW TO GET THE REAL NUMBERS")
    print("=" * 60)
    print("""
  This file does NOT run linters. To get the miss-correlation for YOUR
  REAL tools (not the reconstruction from Block 2):

      pip install -e blindspot/        # package in this repository
      pip install pylint ruff flake8   # any two or three of them
      blindspot probe-python           # builds corpus, runs linters, measures

  probe-python will build the dead-import corpus itself, run the installed
  linters, and compute their miss-correlation. The numbers from the paper
  (pylint x ruff ≈ +0.26; ruff x flake8 ≈ +1.00 — literal duplication) are
  reproduced this way, not by this listing.

  The orthogonal mypy x runtime pair from the paper is NOT reproduced here:
  probe-python deliberately does not execute code (static linters only).
""")


if __name__ == "__main__":
    selftest()
    reconstruction()
    how_to_get_real_numbers()
