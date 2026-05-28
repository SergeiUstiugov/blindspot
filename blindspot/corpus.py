# -*- coding: utf-8 -*-
"""Корпус однозначно мёртвых импортов в естественных синтаксических вариантах.

Все сниппеты содержат импорт, который СЕМАНТИЧЕСКИ мёртв (не используется,
удалён или под мёртвой ветвью) — ground truth известен по построению, не зависит
от инструментов. Спорные случаи (голое имя-выражение, реальный __all__-реэкспорт)
ИСКЛЮЧЕНЫ намеренно: чистота разметки важнее объёма.
"""

DEAD_MODULES = ["os", "sys", "json", "math", "re", "io", "csv", "time"]
# несуществующие модули для try/except-варианта (его ловит pylint, пропускает ruff)
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
    """Возвращает dict {task_id: source}. Все — класс дефекта 'unused_import'."""
    corpus = {}
    for mod in DEAD_MODULES:
        corpus.update(_variants(mod))
    for fm in FAKE_MODULES:
        corpus[f"try_import_{fm}"] = (
            f"try:\n    import {fm}\nexcept ImportError:\n    {fm} = None\nx = 1\n")
    return corpus


DEFECT_CLASS = "unused_import"


# ───────────────────────── второй класс: unused_variable ──────────────────────
# Локальная переменная, которой присвоено значение и которая нигде не читается.
# Ground truth по построению. Включены варианты, где инструменты расходятся
# (переменная цикла ловится pylint, но не F841 у ruff/flake8).

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
    """Возвращает dict {task_id: source} для класса 'unused_variable'.
    NB: вариант reassigned_* НЕ содержит дефекта (переменная читается) —
    он отсеивается на этапе ground truth и служит контролем чистоты."""
    corpus = {}
    for name in VAR_NAMES:
        corpus.update(_var_variants(name))
    return corpus


# отметка, какие варианты реально содержат дефект (ground truth)
def has_defect_var(task_id):
    # reassigned_* — переменная в итоге читается (return name) → дефекта НЕТ
    return not task_id.startswith("reassigned_")


def build_all_classes():
    """Возвращает список (defect_class, {task_id: (source, has_defect)})."""
    imp = {tid: (src, True) for tid, src in build_corpus().items()}
    var = {tid: (src, has_defect_var(tid)) for tid, src in build_corpus_var().items()}
    return [(DEFECT_CLASS, imp), (DEFECT_CLASS_VAR, var)]
