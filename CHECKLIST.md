# Checklist for auditing the reliability of a "generator + checks" pairing

This document is methodology, not code. The `blindspot` package automates only the
**base level** (T1: miss-correlation by defect class). The Pro levels (T2 — external
grounding, T3 — loop stability) remain on the engineer's side: they cannot be
honestly reduced to a single metric, so here they are given as verifiable questions
and schemes from which you build your own modules on top of the core.

Legend: ✅ — automated in `blindspot`; 🔧 — assembled by the engineer following the
scheme below; 📐 — a theoretical criterion, checked by reasoning/manual analysis.

---

## Base level — check independence (T1)

**Question: do your checks actually complement each other, or do they share blind spots?**

- ✅ **B1. Count blind spots, not the number of checks.** For each defect class
  separately, build a miss matrix and compute the pairwise miss-correlation.
  `blindspot probe-python` does this for unused-import and unused-variable;
  `blindspot report misses.csv` — for your matrix.

- ✅ **B2. Never pool defect classes.** The correlation is computed strictly within
  one class Z. Pooling produces a spurious correlation (Simpson). The tool enforces
  this; if you build your own corpus — enforce it too.

- ✅ **B3. Flag duplicates and partial overlaps.** A pair with corr ≈ +1 is a
  duplicate (remove one from CI). A pair with corr near 0 and a CI covering zero is
  independent (keeping both is useful). `blindspot` reports this as "stack composition
  advice."

- 🔧 **B4. Your own defect class.** To add a class (e.g. "name shadowing,"
  "unreachable code") you need: (a) a corpus of snippets with **unambiguous** ground
  truth; (b) linter wrappers narrowed to the rules of that class (see
  `linters.RULES`). Corpus requirement: the defect must be certain by construction,
  not "by eye."

- 🔧 **B5. Corpus cleanliness control.** Include variants WITHOUT a defect (like
  `reassigned_*` in the unused_variable class) — if a tool "catches" a defect where
  there is none, your ground truth is contaminated. Remember the -0.84 artifact: a
  dirty labeling produces a spurious correlation in either direction.

---

## Pro level — external grounding of a check (T2 / DPI)

**Question: does the check look at something external to the generator — or only at the generator's own output?**

`blindspot` does NOT measure this: DPI is a structural property of the data flow, not
reducible to miss-correlation. It is checked by analyzing the architecture:

- 📐 **P1. Where does the check get its input?** If input(V) ⊆ output(M) (the check
  reads only what the generator itself produced — its "explanation," "certificate,"
  "chain-of-thought"), then V is structurally blind to what M filtered out. This is a
  direct consequence of the data-processing inequality.

- 🔧 **P2. Give the check an external channel.** Real tests, source data, an
  independent reference, a separate judge model on different data. A practical check:
  can you name an information source the check has that the generator does not? If
  not — the check is decorative.

- 🔧 **P3. For LLM pipelines:** grounding / RAG / sandbox execution are the ways to
  give V an external footing. A model self-reviewing its own answer without external
  data does not satisfy T2.

---

## Pro level — stability of the iterative loop (T3)

**Question: does the loop "generated → checked → fixed → again" converge or diverge?**

`blindspot` does NOT measure this: it requires a dynamic run of the loop, not a static
measurement of misses. A scheme for your own module:

- 📐 **T-1. Is there an external reference in the loop?** If fixes are evaluated only
  by the system's agreement with itself (no external criterion of truth), the loop
  tends to diverge — growing in self-consistency while drifting from reality.

- 🔧 **T-2. Monitor drift.** Run the loop for N iterations on a test set and track a
  quality metric against an **external** reference (not against the previous
  iteration). Rising consistency with falling external quality is a divergence signal
  (formally ρ(Q) ≥ 1).

- 🔧 **T-3. Limit self-reference.** Do not train/tune the system only on its own
  outputs without external labeling. This is the most common way to lose stability.

---

## How the package maps onto the checklist

`blindspot` covers items **B1–B3 fully and B4–B5 as a template** (you add classes
following the scheme). Items P* and T* are methodology: the tool provides the core
(the metric and corpus discipline) on top of which you build your own checks for a
specific stack. This is intentional: you can honestly automate only what reduces to a
measurable quantity with clean ground truth; the rest requires engineering judgment,
and pretending to be a button here would be the very overclaim the whole methodology
argues against.
