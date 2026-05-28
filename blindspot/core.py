# -*- coding: utf-8 -*-
"""
core.py — measurement core: miss correlation of a pair of checks per defect class Z.

WHAT IT DOES:
  Takes a miss CSV and within EACH defect class Z computes three metrics
  (no pooling across Z — pooling produces spurious correlation, Simpson's paradox):
    (1) pairwise miss correlation of methods (phi);
    (2) joint-miss vs product of marginals (how many times more likely the joint miss
        is than under independence);
    (3) total correlation / multi-information (information-theoretic analogue of
        "the joint error picture factors into independent parts").
  Each metric comes with a SHUFFLE control (breaks inter-method dependence while
  preserving marginals → estimates finite-sample bias) and a bootstrap CI.

CSV FORMAT:
  task_id, defect_class, ground_truth_defect, miss_<method1>, miss_<method2>, ...
  miss_* ∈ {0,1}, 1 = method MISSED a real defect (false-negative).
  Only rows with ground_truth_defect == 1 are used for analysis.

VERDICT (fixed before the run):
  Independence for Z only if ALL of: pairwise corr ≈ 0 (CI includes 0)
  AND joint ≈ product (ratio CI includes 1) AND debiased TC ≈ 0 (CI includes 0).
  Otherwise — methods are conditionally dependent on Z (they share a common blind spot).

USAGE (via package CLI):
  blindspot selftest
  blindspot report misses.csv
  blindspot report misses.csv --n-boot 2000 --seed 0
"""
import argparse
import sys
import numpy as np

# ───────────────────────────── basic statistics ───────────────────────────────

def _phi_corr(x, y):
    """Correlation of two binary vectors (phi = Pearson on {0,1})."""
    if x.std() == 0 or y.std() == 0:
        return np.nan          # zero variance → correlation is undefined
    return float(np.corrcoef(x, y)[0, 1])


def _binary_entropy_bits(col):
    """H(m_i) in bits for a binary column."""
    p = col.mean()
    return _entropy_from_probs(np.array([1 - p, p]))


def _entropy_from_probs(p):
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def _joint_entropy_bits(M):
    """H(m_1,...,m_k) from observed column patterns of M [n,k]."""
    n = M.shape[0]
    # encode pattern as integer
    weights = (1 << np.arange(M.shape[1]))
    codes = (M * weights).sum(axis=1)
    _, counts = np.unique(codes, return_counts=True)
    return _entropy_from_probs(counts / n)


def total_correlation_bits(M):
    """TC = Σ H(m_i) − H(joint). TC=0 ⇔ full independence ⇔ rank-1 tensor."""
    sum_marg = sum(_binary_entropy_bits(M[:, i]) for i in range(M.shape[1]))
    return sum_marg - _joint_entropy_bits(M)


def joint_vs_product(M):
    """P(all missed) and Π P(each missed); ratio = joint/product."""
    joint = float((M.sum(axis=1) == M.shape[1]).mean())
    product = float(np.prod(M.mean(axis=0)))
    ratio = joint / product if product > 0 else np.nan
    return joint, product, ratio


def _shuffle_independent(M, rng):
    """Shuffle each column independently → break inter-method dependence,
    preserve marginals. Estimates finite-sample floor of the metrics."""
    out = M.copy()
    for i in range(out.shape[1]):
        out[:, i] = rng.permutation(out[:, i])
    return out


# ───────────────────────────── bootstrap wrapper ──────────────────────────────

def _bootstrap_ci(M, stat_fn, n_boot, rng, alpha=0.05):
    """Percentile CI of statistic stat_fn(M) via row resampling."""
    n = M.shape[0]
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        v = stat_fn(M[idx])
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            vals.append(v)
    if not vals:
        return (np.nan, np.nan)
    lo = float(np.percentile(vals, 100 * alpha / 2))
    hi = float(np.percentile(vals, 100 * (1 - alpha / 2)))
    return (lo, hi)


# ───────────────────────────── analysis for a single Z ────────────────────────

def analyze_class(M, methods, n_boot, rng, alpha=0.05):
    """All metrics within a single class Z. M [n,k] binary, k=len(methods)."""
    n = M.shape[0]
    res = {"n": n, "marginal_miss": {m: float(M[:, i].mean())
                                     for i, m in enumerate(methods)}}

    # (1) pairwise correlations + shuffle
    pair = {}
    for i in range(len(methods)):
        for j in range(i + 1, len(methods)):
            obs = _phi_corr(M[:, i], M[:, j])
            sh = _phi_corr(*[_shuffle_independent(M[:, [i, j]], rng)[:, c]
                             for c in (0, 1)])
            ci = _bootstrap_ci(M[:, [i, j]],
                               lambda A: _phi_corr(A[:, 0], A[:, 1]),
                               n_boot, rng, alpha)
            pair[f"{methods[i]}|{methods[j]}"] = {
                "corr": obs, "corr_ci": ci, "shuffle_corr": sh}
    res["pairwise"] = pair

    # (2) joint-miss vs product (all methods)
    joint, product, ratio = joint_vs_product(M)
    ratio_ci = _bootstrap_ci(M, lambda A: joint_vs_product(A)[2], n_boot, rng, alpha)
    res["joint_vs_product"] = {"joint": joint, "product": product,
                               "ratio": ratio, "ratio_ci": ratio_ci}

    # (3) total correlation, debiased by shuffle
    tc_obs = total_correlation_bits(M)
    tc_shuf = np.mean([total_correlation_bits(_shuffle_independent(M, rng))
                       for _ in range(min(50, n_boot))])
    debiased = tc_obs - tc_shuf
    tc_ci = _bootstrap_ci(
        M, lambda A: total_correlation_bits(A)
        - np.mean([total_correlation_bits(_shuffle_independent(A, rng))
                   for _ in range(20)]),
        n_boot, rng, alpha)
    res["total_correlation"] = {"tc_obs_bits": tc_obs, "tc_shuffle_bits": tc_shuf,
                                "tc_debiased_bits": debiased, "tc_debiased_ci": tc_ci}
    return res


def verdict_for_class(res, alpha=0.05):
    """Verdict rule, fixed before the run."""
    # corr: do all CIs include 0?
    corr_ok = all((p["corr_ci"][0] <= 0 <= p["corr_ci"][1])
                  for p in res["pairwise"].values()
                  if not np.isnan(p["corr_ci"][0]))
    # ratio: does CI include 1?
    rci = res["joint_vs_product"]["ratio_ci"]
    ratio_ok = (not np.isnan(rci[0])) and (rci[0] <= 1 <= rci[1])
    # TC: does CI include 0?
    tci = res["total_correlation"]["tc_debiased_ci"]
    tc_ok = (not np.isnan(tci[0])) and (tci[0] <= 0 <= tci[1])
    independent = corr_ok and ratio_ok and tc_ok
    return {"independent": independent,
            "corr_ok": corr_ok, "ratio_ok": ratio_ok, "tc_ok": tc_ok}


def evaluate_candidate(res, candidate, accepted, n, ci_width_max=0.6):
    """Incremental check: should candidate be added to the already accepted set?

    Takes the already-computed res['pairwise'] and examines the miss correlation of
    the candidate with EACH accepted validator. Verdict uses the same threshold as
    the ranking:
      - 'duplicate'   : there is an accepted validator whose corr CI is strictly > 0.8
      - 'complements' : for all accepted validators the corr CI covers 0
      - 'weak'        : partial overlap with at least one
      - 'inconclusive': too little data / wide CI — do NOT trust the conclusion

    Returns a dict with the verdict and per-pair breakdown. inconclusive takes priority:
    on a small sample one cannot declare that a candidate complements the set.
    """
    pairs = res["pairwise"]

    def _find(a, b):
        return pairs.get(f"{a}|{b}") or pairs.get(f"{b}|{a}")

    per_member, widths = [], []
    dup_with, weak_with = [], []
    for m in accepted:
        p = _find(candidate, m)
        if p is None:
            continue
        lo, hi = p["corr_ci"]
        if lo != lo:  # nan
            per_member.append((m, float("nan"), "n/a"))
            continue
        widths.append(hi - lo)
        if lo > 0.8:
            rel = "duplicate"
            dup_with.append(m)
        elif lo > 0:
            rel = "weak"
            weak_with.append(m)
        else:
            rel = "independent"
        per_member.append((m, p["corr"], rel))

    too_wide = any(w > ci_width_max for w in widths) or not widths
    if n < 10 or too_wide:
        verdict = "inconclusive"
    elif dup_with:
        verdict = "duplicate"
    elif weak_with:
        verdict = "weak"
    else:
        verdict = "complements"

    return {"verdict": verdict, "candidate": candidate, "accepted": list(accepted),
            "per_member": per_member, "dup_with": dup_with, "weak_with": weak_with}


def print_candidate_eval(ev, z):
    """Human-readable output of evaluate_candidate."""
    v = ev["verdict"]
    cand = ev["candidate"]
    print(f"\n-- candidate '{cand}' vs accepted set {ev['accepted']} (class {z}) --")
    for m, corr, rel in ev["per_member"]:
        cc = "n/a" if corr != corr else f"{corr:+.2f}"
        print(f"    vs {m}: corr={cc}  ({rel})")
    if v == "inconclusive":
        print(f"  VERDICT: INCONCLUSIVE — too little data. Expand the corpus, "
              f"do not draw conclusions about the candidate yet.")
    elif v == "duplicate":
        print(f"  VERDICT: DUPLICATES {ev['dup_with']} — not worth adding, "
              f"coverage for {z} will not increase.")
    elif v == "weak":
        print(f"  VERDICT: partially overlaps with {ev['weak_with']} — "
              f"adds marginally; decide based on the cost of an extra CI check.")
    else:
        print(f"  VERDICT: COMPLEMENTS the set — independent of all accepted validators, "
              f"worth adding to the stack for {z}.")
    return v



def _print_class(res):
    mm = ", ".join(f"{k}={v:.2f}" for k, v in res["marginal_miss"].items())
    print(f"  marginal miss: {mm}")
    for pair, p in res["pairwise"].items():
        c = p["corr"]
        cs = "nan" if np.isnan(c) else f"{c:+.3f}"
        ci = p["corr_ci"]
        ci_s = "—" if np.isnan(ci[0]) else f"[{ci[0]:+.3f},{ci[1]:+.3f}]"
        print(f"    corr {pair}: {cs} CI{ci_s} (shuffle≈{p['shuffle_corr']:+.3f})"
              if not np.isnan(p["shuffle_corr"]) else
              f"    corr {pair}: {cs} CI{ci_s}")
    jp = res["joint_vs_product"]
    rci = jp["ratio_ci"]
    rci_s = "—" if np.isnan(rci[0]) else f"[{rci[0]:.2f},{rci[1]:.2f}]"
    print(f"    joint={jp['joint']:.4f} product={jp['product']:.4f} "
          f"ratio={jp['ratio']:.2f} CI{rci_s}")
    tc = res["total_correlation"]
    tci = tc["tc_debiased_ci"]
    tci_s = "—" if np.isnan(tci[0]) else f"[{tci[0]:+.3f},{tci[1]:+.3f}]"
    print(f"    TC debiased={tc['tc_debiased_bits']:+.3f} bits CI{tci_s} "
          f"(obs={tc['tc_obs_bits']:.3f}, shuffle={tc['tc_shuffle_bits']:.3f})")




# ───────────────────────────── loading the miss matrix ────────────────────────

def load_misses(csv_path):
    """Reads CSV (task_id, defect_class, ground_truth_defect, miss_<m>...).
    Returns (data: {z: ndarray[n,k]}, methods: list[str], notes: list[str]).
    Empty fields = unavailable validator: method with no data is excluded,
    rows with partial missing values are dropped."""
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split(",")
        for line in f:
            if line.strip():
                rows.append(line.rstrip("\n").split(","))
    col = {name: i for i, name in enumerate(header)}
    for need in ("defect_class", "ground_truth_defect"):
        if need not in col:
            raise ValueError(f"CSV has no column {need}")
    methods = [h[len("miss_"):] for h in header if h.startswith("miss_")]
    if len(methods) < 2:
        raise ValueError("need >=2 miss_<method> columns")
    miss_idx = [col[f"miss_{m}"] for m in methods]
    notes = []
    have = {m: False for m in methods}
    raw_data = {}
    for r in rows:
        if r[col["ground_truth_defect"]].strip() != "1":
            continue
        z = r[col["defect_class"]]
        vals = [r[i].strip() for i in miss_idx]
        for m, v in zip(methods, vals):
            if v != "":
                have[m] = True
        raw_data.setdefault(z, []).append(vals)
    keep = [i for i, m in enumerate(methods) if have[m]]
    dropped = [m for m in methods if not have[m]]
    if dropped:
        notes.append(f"excluded methods with no data: {', '.join(dropped)}")
    methods = [methods[i] for i in keep]
    if len(methods) < 2:
        raise ValueError("fewer than 2 methods with data after filtering")
    data, skipped = {}, 0
    for z, lst in raw_data.items():
        for vals in lst:
            sub = [vals[i] for i in keep]
            if "" in sub:
                skipped += 1
                continue
            data.setdefault(z, []).append([int(v) for v in sub])
    if skipped:
        notes.append(f"skipped rows with incomplete data: {skipped}")
    return {z: __import__("numpy").array(v, dtype=int) for z, v in data.items()}, methods, notes


def analyze_csv(csv_path, n_boot=2000, seed=0, alpha=0.05, verbose=True):
    """Independence analysis per Z. Returns {z: {'res':..,'verdict':..,'n':..}}."""
    import numpy as np
    rng = np.random.default_rng(seed)
    data, methods, notes = load_misses(csv_path)
    if verbose:
        print("=" * 70)
        print("BLINDSPOT — miss correlation of validators per defect class Z")
        print("=" * 70)
        for nt in notes:
            print(f"  ! {nt}")
        print(f"Methods: {', '.join(methods)}")
        print(f"Z classes: {len(data)} | bootstrap={n_boot}, seed={seed}\n")
    out = {}
    for z, M in sorted(data.items()):
        n = M.shape[0]
        if verbose:
            print(f"-- Z = {z}  (n={n}) " + "-" * 30)
            if n < 10:
                print("  ! n<10 — sample too small, CIs are NOT interpretable as 'independent'.")
        res = analyze_class(M, methods, n_boot, rng, alpha)
        v = verdict_for_class(res, alpha)
        # fraction of joint misses in corpus — determines the magnitude of φ
        both_miss = float((M.sum(axis=1) == M.shape[1]).mean())
        # pairwise correlation CI width — for the INCONCLUSIVE verdict
        ci_widths = [p["corr_ci"][1] - p["corr_ci"][0]
                     for p in res["pairwise"].values()
                     if p["corr_ci"][0] == p["corr_ci"][0]]  # exclude nan
        max_ci_width = max(ci_widths) if ci_widths else float("nan")
        inconclusive = (n < 10) or (max_ci_width == max_ci_width and max_ci_width > 0.6)
        if verbose:
            _print_class(res)
            if inconclusive:
                tag = "INCONCLUSIVE — too little data (expand the corpus)"
            elif v["independent"]:
                tag = "INDEPENDENT"
            else:
                tag = "DEPENDENT"
            print(f"  VERDICT Z={z}: {tag}  "
                  f"[corr_ok={v['corr_ok']} ratio_ok={v['ratio_ok']} tc_ok={v['tc_ok']}]")
            # guard against the "φ as a fact" error: φ is governed by corpus composition
            print(f"  ! fraction of joint misses in corpus = {both_miss:.0%}. "
                  f"If this does not reflect your real code, absolute φ is not portable —")
            print(f"    only the QUALITATIVE conclusion transfers (independent / overlap / duplicates).\n")
        v["inconclusive"] = bool(inconclusive)
        v["both_miss_frac"] = both_miss
        out[z] = {"res": res, "verdict": v, "n": int(n), "methods": methods}
    if verbose:
        print("Status: [NUMERICALLY] with honest controls, NOT [PROVEN]. "
              "Ground truth cleanliness is your responsibility (see README).")
    return out



def make_independent(n, marginals, rng):
    """Each method misses independently with its own probability."""
    return np.column_stack([rng.random(n) < p for p in marginals]).astype(int)


def make_dependent(n, base, hard_frac, rng):
    """Shared latent factor 'hard defect': with probability hard_frac ALL methods
    miss together; otherwise — independently with base probability.
    This produces strong positive miss correlation."""
    k = len(base)
    hard = rng.random(n) < hard_frac
    M = np.column_stack([rng.random(n) < base[i] for i in range(k)]).astype(int)
    M[hard, :] = 1
    return M


def run_selftest(n_boot, seed):
    rng = np.random.default_rng(seed)
    methods = ["A", "B", "C", "D"]
    n = 120
    print("=" * 70)
    print("TOOL SELFTEST (synthetic; the tool must both pass and fail)")
    print("=" * 70)

    # A. deliberately INDEPENDENT
    print("\n--- A. deliberately INDEPENDENT misses (marginals 0.3/0.4/0.5/0.35) ---")
    Ma = make_independent(n, [0.30, 0.40, 0.50, 0.35], rng)
    ra = analyze_class(Ma, methods, n_boot, rng)
    _print_class(ra)
    va = verdict_for_class(ra)
    print(f"  → verdict: {'INDEPENDENT' if va['independent'] else 'DEPENDENT'} "
          f"(expected: INDEPENDENT)")

    # B. deliberately DEPENDENT
    print("\n--- B. deliberately DEPENDENT misses (shared 'hard defect', frac=0.35) ---")
    Mb = make_dependent(n, [0.15, 0.15, 0.15, 0.15], 0.35, rng)
    rb = analyze_class(Mb, methods, n_boot, rng)
    _print_class(rb)
    vb = verdict_for_class(rb)
    print(f"  → verdict: {'INDEPENDENT' if vb['independent'] else 'DEPENDENT'} "
          f"(expected: DEPENDENT)")

    # outcome: the tool must distinguish A from B
    ok = va["independent"] and (not vb["independent"])
    print("\n" + "=" * 70)
    if ok:
        print("SELFTEST PASSED: the tool distinguishes the independent case from the dependent one.")
        print("  (A→INDEPENDENT, B→DEPENDENT — as required)")
    else:
        print("SELFTEST FAILED: the tool does NOT distinguish A from B → do NOT run on real data.")
        print(f"  A independent={va['independent']} (expected True), "
              f"B independent={vb['independent']} (expected False)")
    print("=" * 70)
    return 0 if ok else 1


