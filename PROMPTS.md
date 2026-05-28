# Building a harness for your stack with an LLM

`blindspot` is the measurement core: it computes the miss-correlation over a matrix
you give it. To obtain such a matrix for **your** tools you need a harness: adapters
for your linters, a corpus for your defect class, and matrix assembly. This harness
is convenient to generate with an LLM (Perplexity, Claude, etc.).

**How this closes the loop honestly.** The LLM generates *code and data*, but the
point of measurement and decision remains `blindspot` — it looks at the **actual
linter misses on the corpus**, not at the model's word. This is a direct consequence
of T2/DPI from the paper: the check relies on external data (run results + ground
truth), not on the generator's explanation. Here the LLM builds the harness but does
not substitute itself for the measurement.

> **Important for compatibility.** The prompts below already fix the core's contract.
> Do not change the return format (`1=missed, 0=caught, None=unavailable`) or the CSV
> format in them — otherwise the generated code will not connect to
> `blindspot report`. The contract is repeated in every prompt on purpose. All six
> prompts are verified: a harness assembled from them is read by `blindspot report`
> without edits.

---

## The core contract (what we generate against)

The miss matrix is a CSV of exactly this form (read by `blindspot report`):

```
task_id,defect_class,ground_truth_defect,miss_<tool1>,miss_<tool2>
T01,unused_variable,1,1,0
T02,unused_variable,1,0,0
T03,unused_variable,0,,
```

- `ground_truth_defect` ∈ {0,1} — whether the case actually has a defect (only `=1` rows are analyzed);
- `miss_<tool>` ∈ {0,1} — **1 = the tool MISSED the defect** (false negative), 0 = caught;
- empty field — the tool is unavailable/inapplicable to the row.

A tool adapter returns **`1` (missed) / `0` (caught) / `None` (unavailable)**.
Ground truth is kept **separately** (in the corpus data), not as a marker inside the
code — a marker in the code would tip off the tools and contaminate the measurement.

---

## Prompt 1 — adapter for your linter

```
I have a static analysis tool for Python code.
  Check: [what it looks for, e.g. "unused variables"]
  Invocation: my_linter --check {path}

Write a Python adapter function:

  def run_my_linter(path: str) -> int | None:
      ...

The return contract is STRICTLY as follows (do not change it — it is the external core's format):
  1    — the tool MISSED the defect (no warning where a defect exists)
  0    — the tool caught the defect (emitted a relevant warning)
  None — the tool is unavailable/inapplicable (e.g. crashed with a parse error)

Requirements:
  - run via subprocess, handle a nonzero exit code correctly;
  - narrow the output to the rules of EXACTLY this defect class (via linter flags),
    so that background noise — docstrings, line length — is NOT counted as "caught";
  - no external dependencies, standard library only.

Return only the function code.
```

## Prompt 2 — corpus generator for your defect class

```
Build a mini-corpus of Python snippets to audit an ensemble of linters.
Defect class: [e.g. "unhandled exception"]

Ground-truth requirements (critical — the honesty of the measurement depends on this):
  - the defect must be UNAMBIGUOUS BY CONSTRUCTION, not "by eye";
  - include both positives (defect present) and control negatives
    (syntactically similar but NO defect) — they catch labeling contamination;
  - a variety of contexts: in a function, in a class method, in an if/try branch,
    under `if False`, under `TYPE_CHECKING` — so a spread of misses appears.

I need a Python script that returns a dictionary:
  { task_id: (source_code: str, has_defect: bool) }
where has_defect is the ground truth known by construction (True/False).

Do NOT use markers inside the code (no # DEFECT comments) — keep ground truth
separate, in has_defect, so it does not tip off the tools.
Return the finished script.
```

## Prompt 3 — assembling the miss matrix into the core CSV

```
I have:
  - a corpus dictionary { task_id: (source: str, has_defect: bool) };
  - a list of adapters { tool_name: function(path)->int|None }
    (1=missed, 0=caught, None=unavailable).

Write a Python script that:
  1) for each case writes source to a temporary .py file;
  2) runs each adapter, collects the miss values;
  3) writes a CSV STRICTLY in this format (read by the external blindspot core):

     task_id,defect_class,ground_truth_defect,miss_<tool1>,miss_<tool2>,...

     where ground_truth_defect = 1 if has_defect else 0;
     miss_* = the adapter value (empty string if None);
  4) deletes the temporary files.

defect_class is given as a parameter. Standard library only. Return the script.
```

After the run: `blindspot report misses.csv` computes φ, joint/product, and
total correlation and gives a verdict per class — this is the point of measurement.

## Prompt 4 — pair classification (if you want your own report without blindspot)

```
I have the results of pairwise check-audit metrics: for each pair of tools I know
phi (φ miss-correlation) with a 95% CI [phi_lo, phi_hi] and ratio (joint/product)
with a CI [ratio_lo, ratio_hi].

Write a Python function classify_pair(phi, phi_lo, phi_hi, ratio_lo, ratio_hi) -> str
that returns STRICTLY one of:
  "independent"     — the phi CI covers 0 AND the ratio CI covers 1;
  "duplicate"       — phi >= 0.9 and ratio_lo is clearly > 1;
  "weak_dependence" — otherwise, if phi_lo > 0 or ratio_lo > 1;
  "inconclusive"    — if the sample is small and the CI is too wide (phi_hi - phi_lo > 0.6).

Important: "inconclusive" takes priority — small n and a wide CI mean "not enough
data," NOT "independent." Standard library only. Return the function.
```

## Prompt 5 — a Markdown report for CI

```
I need a utility script. Input — a CSV of pairwise metrics:
  checker_a, checker_b, phi, phi_lo, phi_hi, ratio, relation
(relation — from the classifier: independent / weak_dependence / duplicate / inconclusive).

The script should:
  - print to stdout a Markdown table: check A | check B | φ | ratio | relation;
  - then a short summary:
      * relation="duplicate" pairs -> "one of the tools can be removed from CI
        for this defect class";
      * relation="independent" pairs -> "keep both — they give real diversity";
      * relation="inconclusive" pairs -> "too little data, a larger corpus is needed."
  - return a nonzero exit code if there is at least one "duplicate"
    (so the CI step can be made failing).

Standard library only. Return the script.
```

## Prompt 6 — porting the approach to another stack (JS/TS)

```
I want to port the linter-ensemble audit approach from Python to JavaScript/TypeScript
(ESLint, tsc, custom checks).

Provide:
  1) a corpus generator for the class "unused variable": a dictionary
     { task_id: (source, has_defect) }, ground truth by construction, with
     control negatives, WITHOUT markers in the code;
  2) adapters for ESLint and tsc in Node.js — each returning 1/0/None
     (1=missed the defect, 0=caught, None=unavailable), narrowed to the class rules;
  3) a script that produces a CSV in the format
     task_id,defect_class,ground_truth_defect,miss_eslint,miss_tsc
     (ground_truth_defect = 1/0, miss_* = 1/0/empty),
     suitable for `blindspot report`.

Return the adapter code and the CSV assembler.
```

## Prompt 7 — scouting candidate validators for a defect class

The purpose of this prompt is special: the LLM names which checks **exist** for your
defect class (name, command, flag) — but whether they are orthogonal to your stack is
decided not by the LLM but by a run through `blindspot candidate`. So the prompt asks
for **only a list of candidates**, with no "which is best" rating: ranking by
usefulness would be a conclusion drawn from the "model's explanation," i.e. a
violation of T2.

```
I am assembling an ensemble of independent checks for the defect class: [e.g.
"unused import" / "hardcoded secret" / "unhandled exception"].
Language/stack: [Python / JS / Go / ...].

Name the CANDIDATES — tools that can in principle catch this class. For each:
  - name;
  - command to run on a single file;
  - rule/flag that narrows output to exactly this class;
  - type: static (reads the code) or dynamic (EXECUTES the code — tests,
    runtime assertions, property-based).

IMPORTANT, what NOT to do:
  - do not rank the candidates or advise "which is best to add" — that is decided
    by the external measurement on my code, not by you;
  - do not claim they are independent of each other — that is exactly what I will measure.
Just a full list of options with the facts of how to run them.

Output format — a table: name | command | class flag | type (static/dynamic).
```

> **Safety (dynamic candidates).** If the list contains dynamic checks — they
> **execute** code. Run them only in a sandbox/container and only on code you trust:
> executing generated code on your working machine is unsafe. Static candidates do
> not run code. The ready-made probe `blindspot probe-python` deliberately works with
> static tools only; you connect dynamic ones yourself, at your own risk.

### The ensemble-assembly loop (how a candidate becomes accepted)

1. Prompt 7 → a list of candidates for your defect class.
2. You pick one, Prompt 1 → an adapter for it (the 1/0/None contract).
3. Prompt 3 → a miss matrix including the candidate and the already-accepted set.
4. `blindspot candidate misses.csv --candidate X --accepted A,B` → a verdict:
   **complements** the set (include), **duplicates** someone (drop),
   **inconclusive** (expand the corpus, do not decide now).
5. If it complements — the candidate becomes part of the set; take the next one from step 1.

This way the ensemble is assembled from validators each of which has **proven** by a
run that it adds coverage, rather than just sitting in CI. The LLM suggested what
exists; the measurement on your code decided.

---

## Why we hand the harness to the LLM but not the measurement

The LLM is good at generating routine plumbing: adapters, corpus, parsing. But you
**cannot trust it with the independence verdict** — that would be a check based on
the "model's explanation," exactly what violates T2/DPI. So the LLM builds the input,
and `blindspot` issues the verdict on actual misses. And do not forget the safeguard
from the README: small n and a wide CI mean "not enough data," not "independent"; a
dirty ground truth produces an artifact in either direction (the -0.84 story). An
LLM-generated corpus is especially worth checking with control negatives.
