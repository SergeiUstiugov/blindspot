# -*- coding: utf-8 -*-
"""Corpus of unambiguously dead imports in natural syntactic variants.

Every snippet contains an import that is SEMANTICALLY dead (unused, deleted, or
under a dead branch) - the ground truth is known by construction and does not
depend on the tools. Borderline cases (a bare name expression, a real __all__
re-export) are deliberately EXCLUDED: cleanliness of labeling matters more than
volume.
"""

DEAD_MODULES = ["os", "sys", "json", "math", "re", "io", "csv", "time"]
# nonexistent modules for the try/except variant (pylint catches it, ruff misses)
FAKE_MODULES = ["simplejson", "ujson", "cjson", "orjson", "rapidjson",
                "hyperjson", "fastjson", "yajl"]


def _variants(mod):
    return {
        f"plain_{mod}":       f"import {mod}\nx = 1\n",
        f"from_star_{mod}":   (f"from {mod} import *\nx = 1\n"
                               if mod in ("os", "math") else f"import {mod}\nx = 1\n"),
        f"as_alias_{mod}":    f"import {mod} as _m\nx = 1\n",
        f"in_func_{mod}":     f"def g():\n    import {mod}\n    return 1\n",
        f"in_class_{mod}":    f"class C:\n    import {mod}\n    y = 1\n",
        f"del_after_{mod}":   f"import {mod}\ndel {mod}\nx = 1\n",
        f"dead_branch_{mod}": f"import {mod}\nif False:\n    print({mod})\nx = 1\n",
        f"type_guard_{mod}":  ("from typing import TYPE_CHECKING\n"
                               f"if TYPE_CHECKING:\n    import {mod}\nx = 1\n"),
        f"del_in_func_{mod}": f"def f():\n    import {mod}\n    del {mod}\n    return 1\n",
        f"try_in_func_{mod}": (f"def f():\n    try:\n        import {mod}\n"
                               f"    except Exception:\n        {mod} = None\n    return 1\n"),
    }


def build_corpus():
    """Returns dict {task_id: source}. All are defect class 'unused_import'."""
    corpus = {}
    for mod in DEAD_MODULES:
        corpus.update(_variants(mod))
    for fm in FAKE_MODULES:
        corpus[f"try_import_{fm}"] = (
            f"try:\n    import {fm}\nexcept ImportError:\n    {fm} = None\nx = 1\n")
    return corpus


DEFECT_CLASS = "unused_import"


# ============== second class: unused_variable ==============
# A local variable that is assigned a value and is never read.
# Ground truth by construction. Includes variants where the tools disagree
# (a loop variable is caught by pylint but not by F841 in ruff/flake8).

def _var_variants(name):
    return {
        f"plain_assign_{name}":  f"def f():\n    {name} = compute()\n    return 1\n",
        f"tuple_unpack_{name}":  f"def f():\n    {name}, used = pair()\n    return used\n",
        f"loop_var_{name}":      f"def f():\n    for {name} in range(3):\n        pass\n    return 1\n",
        f"aug_then_drop_{name}": f"def f():\n    {name} = 0\n    {name} += 1\n    return 2\n",
        f"reassigned_{name}":    f"def f():\n    {name} = 1\n    {name} = 2\n    return {name}\n",
    }


VAR_NAMES = ["tmp", "buf", "acc", "res", "val", "cnt", "idx", "data"]
DEFECT_CLASS_VAR = "unused_variable"


def build_corpus_var():
    """Returns dict {task_id: source} for the 'unused_variable' class.
    NB: the reassigned_* variant does NOT contain a defect (the variable is read) -
    it is filtered out at the ground-truth stage and serves as a cleanliness control."""
    corpus = {}
    for name in VAR_NAMES:
        corpus.update(_var_variants(name))
    return corpus


# marker for which variants actually contain a defect (ground truth)
def has_defect_var(task_id):
    # reassigned_* - the variable ends up being read (return name) -> NO defect
    return not task_id.startswith("reassigned_")


def build_all_classes():
    """Returns a list (defect_class, {task_id: (source, has_defect)})."""
    imp = {tid: (src, True) for tid, src in build_corpus().items()}
    var = {tid: (src, has_defect_var(tid)) for tid, src in build_corpus_var().items()}
    return [(DEFECT_CLASS, imp), (DEFECT_CLASS_VAR, var)]
