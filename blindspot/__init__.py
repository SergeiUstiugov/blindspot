# -*- coding: utf-8 -*-
"""blindspot — измеряет, делят ли валидаторы слепые зоны (корреляцию промахов
внутри одного класса дефекта). НЕ «фреймворк надёжности ИИ» — узкий измеритель.
См. README: что инструмент делает и, главное, чего НЕ делает."""
from .core import analyze_csv, load_misses, run_selftest, analyze_class, verdict_for_class
from .probe import run as probe_python

__version__ = "0.1.0"
__all__ = ["analyze_csv", "load_misses", "run_selftest",
           "analyze_class", "verdict_for_class", "probe_python"]
