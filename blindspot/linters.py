# -*- coding: utf-8 -*-
"""Обёртки для статических линтеров, параметризованные по классу дефекта.

Каждая обёртка возвращает на сниппете: 1 = ПРОПУСТИЛ дефект (false-negative),
0 = поймал, None = линтер недоступен/упал. Линтеры сужены до правил конкретного
класса дефекта, чтобы фоновый шум (docstring, длина строки) не считался «поймал».

ВАЖНО (кроссплатформенность): линтеры запускаются как `python -m <модуль>`,
а НЕ как голый бинарь. На Windows pylint/ruff/flake8 ставятся как .cmd/.exe,
которые subprocess без shell не находит (FileNotFoundError). Запуск через
sys.executable -m работает одинаково на Windows, Linux и macOS.

Намеренно только СТАТИЧЕСКИЕ линтеры: проба не исполняет проверяемый код.

Набор правил на класс (RULES[класс][линтер]):
  unused_import   — неиспользуемые/мёртвые импорты
  unused_variable — присвоенные, но не читаемые локальные переменные
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

# правила по классам дефектов
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

# имя линтера -> имя импортируемого модуля (для `python -m <модуль>`)
MODULE = {"pylint": "pylint", "ruff": "ruff", "flake8": "flake8"}


def _run(args, timeout=120):
    """Запуск `python -m <args>` кроссплатформенно."""
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
    """Установлен ли линтер — проверка по импортируемости модуля (кроссплатформенно)."""
    mod = MODULE.get(name)
    if mod is None:
        return False
    return importlib.util.find_spec(mod) is not None


def available_linters():
    """Список установленных линтеров (по импортируемости модуля, не по PATH)."""
    return [name for name in REGISTRY if is_installed(name)]


def missing_install_hint(names):
    """Дружелюбная подсказка по установке отсутствующих линтеров."""
    miss = [n for n in names if not is_installed(n)]
    if not miss:
        return ""
    return (f"Не установлены: {', '.join(miss)}. "
            f"Поставьте их в ТЕКУЩЕЕ окружение: pip install {' '.join(miss)}")


def run_on_source(name, source, defect_class="unused_import"):
    """Прогнать линтер name на тексте source для класса defect_class. Вернёт 1/0/None."""
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
