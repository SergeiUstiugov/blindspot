# -*- coding: utf-8 -*-
import sys
"""Python-проба: делят ли установленные статические линтеры слепые зоны?

Строит корпус однозначных дефектов (по нескольким классам с жёстким ground
truth), прогоняет на нём установленные линтеры (pylint / ruff / flake8),
формирует матрицу промахов и считает корреляцию промахов ядром — по КАЖДОМУ
классу отдельно (без пулинга). Дополнительно ранжирует избыточность: какую
проверку можно убрать из стека, не теряя покрытия.
"""
from . import corpus as _corpus
from . import linters as _linters
from . import core as _core


def build_miss_csv(out_path, linters=None, verbose=True):
    """Прогнать все классы корпуса через линтеры, записать единый CSV. Вернёт (csv, used)."""
    used = linters or _linters.available_linters()
    if len(used) < 2:
        all_three = ["pylint", "ruff", "flake8"]
        miss = [n for n in all_three if not _linters.is_installed(n)]
        raise SystemExit(
            "Для пробы нужно минимум 2 установленных линтера.\n"
            f"Сейчас доступно: {used or 'ни одного'}.\n"
            f"Установите недостающие В ТО ЖЕ окружение, где стоит blindspot:\n"
            f"    {sys.executable} -m pip install {' '.join(miss or all_three)}\n"
            "Проверьте: blindspot doctor")
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
        print(f"Корпус: {n_total} сниппетов | классы: {cls_names} | линтеры: {', '.join(used)}")
    return out_path, used


def _redundancy_ranking(report):
    """По матрице корреляций промахов внутри каждого Z строит совет:
    какой линтер избыточен (его промахи сильнее всего скоррелированы с другим,
    т.е. он почти не добавляет нового покрытия). Жадно: помечаем кандидата на
    удаление, если есть пара с corr-ДИ строго выше порога."""
    print("\n" + "=" * 70)
    print("СОВЕТ ПО СОСТАВУ СТЕКА (по каждому классу дефекта отдельно)")
    print("=" * 70)
    for z, data in report.items():
        res = data["res"]
        n = data["n"]
        pairs = res["pairwise"]
        print(f"\n-- класс {z} (n={n}) --")
        # ищем дубликаты (нижняя граница ДИ высокая) и независимые
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
            print(f"  • {a} ~ {b}: corr={c:+.2f} — ДУБЛИКАТЫ. "
                  f"Один из двух можно убрать из CI без потери покрытия по {z}.")
        for a, b, c in weak:
            print(f"  • {a} ~ {b}: corr={c:+.2f} — частичное перекрытие. "
                  f"Дополняют друг друга лишь отчасти; держать оба оправдано слабо.")
        for a, b, c in indep:
            print(f"  • {a} ~ {b}: corr={c:+.2f} — независимы, дополняют друг друга. "
                  f"Держать оба полезно.")
        if n < 10:
            print(f"  ! n<10 по классу {z}: совет — ориентир, не вердикт.")


def run(out_csv="blindspot_misses.csv", n_boot=2000, seed=0, verbose=True):
    csv_path, used = build_miss_csv(out_csv, verbose=verbose)
    report = _core.analyze_csv(csv_path, n_boot=n_boot, seed=seed, verbose=verbose)
    if verbose:
        _redundancy_ranking(report)
        print(f"\nМатрица промахов сохранена: {csv_path}")
    return report
