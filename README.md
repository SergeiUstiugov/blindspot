# blindspot

**Auditing the independence and redundancy of code checks:** it shows which linters
in your stack complement each other and which share common blind spots (and are
therefore redundant). It measures this from data — the miss-correlation for each
defect class separately — rather than by eye.

A narrow but honest tool: it automates exactly one level of the audit (check
independence, T1). It does NOT measure the external grounding of checks (T2) or the
stability of iterative loops (T3) — those are moved into the methodological
[CHECKLIST.md](CHECKLIST.md) as schemes you use to build your own checks. Read the
"Limits" section before drawing conclusions.

## Why

A stack of checks (linters, type checkers, tests) reduces the risk of missing a
defect only if the tools' errors are independent. If two checks go blind in the same
places, the second adds almost no protection — you pay CI time while coverage does
not grow. `blindspot` answers whether they are actually independent and directly
advises what can be removed from the stack.

A concrete out-of-the-box example: on unused imports and variables, `ruff` and
`flake8` give a miss-correlation of **+1.00** — they literally duplicate each other
(ruff reimplements the pyflakes rules that flake8 is built on). One of them is
redundant in CI. `pylint` differs from both (+0.26…+0.33) — it partially complements
them. `blindspot probe-python` shows this in seconds.

## Installation

```bash
pip install -e .
# for the Python probe — any two of (install into the SAME environment):
pip install pylint ruff flake8
```

Linters are invoked via `python -m <linter>`, so they work the same on Windows,
Linux, and macOS — even if the binaries are not on PATH. The key requirement is that
they are installed in the same environment (venv) as blindspot.

## Quick start

```bash
# 0. Check the environment (Python, encoding, which linters are visible)
blindspot doctor

# 1. REQUIRED: confirm the meter distinguishes a known-independent
#    case from a known-dependent one
blindspot selftest

# 2. Ready-made probe: builds a defect corpus (dead imports + unused
#    variables), runs the installed linters, computes the miss-correlation
#    for each class, and advises what is redundant in the stack
blindspot probe-python

# 3. Report on your own miss matrix (format below).
#    report runs selftest itself as a gate and refuses to compute if it fails.
blindspot report misses.csv

# 4. Evaluate a NEW candidate validator against an already-accepted set:
#    complements / duplicates / inconclusive (for building an ensemble for your stack)
blindspot candidate misses.csv --candidate flake8 --accepted pylint,ruff
```

> **Windows: if the output is garbled** — the console is not in UTF-8. Run
> `set PYTHONUTF8=1` (or `chcp 65001`) before the command. `blindspot doctor`
> diagnoses this and tells you what to do.

`article_listing.py` in the root is a self-contained listing (numpy only): the
metric + selftest + arithmetic reproduction, without installing the package. Handy
to attach to a paper or to read the whole algorithm at once.

Example `probe-python` output (pylint + ruff + flake8):

```
  corr pylint|ruff:   +0.261 CI[+0.047,+0.468]
  corr pylint|flake8: +0.261 CI[+0.056,+0.451]
  corr ruff|flake8:   +1.000 CI[+1.000,+1.000]   <- ruff and flake8 duplicate each other
```

## Miss matrix format (for `report`)

CSV, one row per (item, defect):

```
task_id,defect_class,ground_truth_defect,miss_pylint,miss_ruff
T01,unused_import,1,1,0
T02,unused_import,1,0,0
```

- `defect_class` — the defect class Z; computed **separately for each class**;
- `ground_truth_defect` in {0,1} — whether the item actually has a defect (only `=1` rows are used);
- `miss_<tool>` in {0,1} — **1 = the tool MISSED** a real defect (false negative);
- empty field = the tool is unavailable on that row (the method is excluded from the analysis).

## What code can be audited

Short answer: **the analyzed code can be in any language.** It helps to distinguish
three different "codes," each with its own answer.

**1. The `blindspot` core — Python (numpy).** The tool itself is written in
Python 3.9+. There is no reason to port it to another language: the core is tiny
(phi-correlation, joint/product, bootstrap — tens of lines), and a port gains
nothing.

**2. The analyzed code — any language.** `blindspot` does not parse sources itself —
it works with a **miss matrix** (the CSV above: missed/caught). Where the matrix
came from is irrelevant to it. So you can audit checks for anything:
JavaScript/TypeScript (ESLint, tsc), Go (golangci-lint, go vet), Rust (clippy), Java
(SpotBugs, PMD) — as long as you run the tools on a corpus and obtain "caught/missed."
The ready-made `probe-python` covers only Python linters (pylint / ruff / flake8)
out of the box — that is the only language-specific part. For another stack you build
the matrix yourself.

**3. The harness for your stack — in your stack's language.** Adapters (run your
linter, return 1/0/None) and the corpus generator are naturally written in the
language of the analyzed code: for JS/TS — Node.js, for Go — Go. The only hard
requirement is that the output must be CSV in the required format. Prompt 6 in
[PROMPTS.md](PROMPTS.md) generates ESLint and tsc adapters in Node.js that write a
compatible CSV.

**The trust boundary runs along the CSV.** The core is fixed and language-agnostic
at the input; the perimeter (the adapters) can be in any language; between them is a
simple text contract. So "porting to another stack" is not rewriting the tool but
writing adapters that feed the same core.

An honest caveat: the question is less "is the language supported" and more **does
your stack have two genuinely independent checks for one defect class.** If not (one
check catches everything, the other nothing), the measurement degenerates — zero
variance, the correlation is undefined. This depends not on the language but on what
you have running in CI.

## Metrics and verdict

Within each class Z, three coherent metrics are computed, all with a bootstrap CI and
a shuffle control (shuffling destroys the cross-tool relationship while preserving
the marginals — it estimates the finite-sample floor):

1. **phi miss-correlation** — pairwise;
2. **joint / product** — how many times more often a joint miss occurs than the product of the marginals;
3. **total correlation** (debiased) — the information-theoretic analogue of "the joint error picture factorizes into independent parts."

A verdict of "independent" is reached **only if all three CIs simultaneously** cover
the neutral value (0, 1, 0). Otherwise — dependent, or there was not enough data.

## Three safeguards — read before trusting the verdict

**1. Never pool different defect classes.** The correlation is computed strictly
within one `defect_class`. Mixing classes triggers Simpson's paradox and a spurious
correlation: tools that each catch "their own" class look correlated when pooled. The
tool enforces this — do not bypass it by merging classes by hand.

**2. Small n + a wide CI != "independent".** When `n < 10` the tool prints a warning
and marks the verdict inconclusive. A near-zero correlation on a tiny sample means
"not enough power," not "independence proven."

**3. The tool correlates whatever you give it.** If the miss matrix is built on
contaminated ground truth, it will honestly compute an **artifact**. A real case from
developing this tool: the first version of the test corpus gave a correlation of
-0.84 ("strong dependence!"), but that was an artifact of how defects were
distributed across tools, not a property of them. After rebuilding the corpus the
"dependence" vanished. A dramatic **negative** result is just as much a candidate for
being an artifact as a beautiful positive one. The cleanliness of the labeling is on
you.

### These safeguards are built into the behavior, not just the documentation

- **selftest as a gate.** `blindspot report` first runs the core selftest and
  **refuses to compute** if it does not pass. You can override only deliberately with
  the `--skip-selftest` flag. You should not trust the numbers until the tool has
  proven it can tell an independent case from a dependent one.
- **INCONCLUSIVE by default.** With small n or a wide confidence interval the verdict
  is "INCONCLUSIVE — not enough data," **not** "independent." A small sample is not
  allowed to declare independence; it overrides a green light.
- **Corpus-composition warning.** Next to the verdict, the share of joint misses in
  the corpus is printed. φ is driven by this share: pack the corpus with "hard" cases
  where both tools go blind together and φ will rise. So transfer only the
  **qualitative** conclusion (independent / overlapping / duplicate), not the φ value
  itself, if the corpus composition does not reflect your real code.

## Broader audit: a checklist

`blindspot` automates the **base level** of the audit — check independence (T1):
miss-correlation, finding duplicates, and advice on stack composition. These are
items B1–B3 of the methodological [CHECKLIST.md](CHECKLIST.md), plus B4–B5 as a
template (you add your own defect class following the scheme in `linters.RULES` and
`corpus.py`).

The broader levels — the external grounding of a check (T2/DPI) and the stability of
the iterative loop (T3) — are given in the checklist as verifiable questions and
schemes, **not** as package functions. They cannot be honestly reduced to a single
metric, so pretending to be a button here would be an overclaim. The checklist shows
how to build such checks on top of the core for your stack.

To build a miss matrix for **your** linters (not just the ready-made pylint / ruff /
flake8), [PROMPTS.md](PROMPTS.md) has a set of LLM prompts: they generate adapters,
a corpus, and CSV assembly strictly under the core's contract, so the output is read
by `blindspot report` right away. The LLM builds the harness — but the point of
measurement remains the run on a real corpus, not the model's word (this is T2/DPI in
practice).

### Building a validator ensemble for your stack

A separate loop — for choosing which checks to keep at all. Prompt 7 (the scout) in
`PROMPTS.md` asks the LLM to name **candidates** for your defect class: name, command,
flag — but without rating "which is best" (the measurement decides that, not the
model). Then each candidate is tested for orthogonality to your set:

```bash
blindspot candidate misses.csv --candidate <new> --accepted <your set, comma-separated>
```

The verdict is **complements** (add to the stack), **duplicates** a specific member
(drop it), or **inconclusive** (expand the corpus, do not decide now). This way the
ensemble is assembled from checks each of which has proven by a run that it adds
coverage. The LLM suggested what exists; the measurement decided. If the candidates
are dynamic (tests, runtime checks) — they execute code, so run them only in a
sandbox (see the caveat in PROMPTS.md).

## Limits — what the tool does NOT do

- It does **not** judge the reliability of the system as a whole — only the miss-correlation of checks by defect class (the T1 level). T2/T3 are in [CHECKLIST.md](CHECKLIST.md) as methodology, not as functions.
- It does **not** build ground truth for you. The probe does this for classes with unambiguous labeling (dead import, unused variable); for your own classes you prepare the miss matrix.
- It does **not** execute your code. The probe uses only static linters (pylint / ruff / flake8); tools that require running code are excluded for safety reasons.
- It does **not** replace any linter — it measures their overlap, it does not find defects.

## Status

The meter is calibrated on synthetic data (`blindspot selftest`: it calls a
known-independent pair independent and a known-dependent pair dependent). The numbers
on real linters are reproducible (`probe-python`), but this is a **measurement on
small corpora**: the confidence intervals are wide, and the magnitude of the
dependence depends on the corpus composition. A working tool with an honestly drawn
scope, not a proof of general claims.

Extracted from a research project as a standalone utility; no theoretical framework
is required to use it.

## License

MIT — use freely.
