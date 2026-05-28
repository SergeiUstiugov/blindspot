# -*- coding: utf-8 -*-
"""CLI: blindspot {selftest | report <csv> | probe-python}."""
import argparse
import sys

from . import core, probe
from . import linters as _linters


def _doctor():
    """Диагностика окружения: Python, кодировка, линтеры. Возвращает exit code."""
    print("=" * 60)
    print("BLINDSPOT DOCTOR — проверка окружения")
    print("=" * 60)
    print(f"Python:     {sys.version.split()[0]}  ({sys.executable})")
    enc = (sys.stdout.encoding or "").lower()
    print(f"Кодировка:  stdout={sys.stdout.encoding}")
    if enc and "utf" not in enc:
        print("  ! ВНИМАНИЕ (обычно Windows): вывод не UTF-8 — возможны кракозябры.")
        print("    Лечится: set PYTHONUTF8=1   (или chcp 65001) перед запуском.")
    print("\nЛинтеры (проверка через `python -m`, не по PATH):")
    avail = []
    for name in ("pylint", "ruff", "flake8"):
        ok = _linters.is_installed(name)
        print(f"  [{'OK ' if ok else '   '}] {name}" + ("" if ok else "  — не установлен"))
        if ok:
            avail.append(name)
    print("")
    if len(avail) >= 2:
        print(f"Готово: доступно {len(avail)} линтера — можно запускать `blindspot probe-python`.")
        return 0
    miss = [n for n in ("pylint", "ruff", "flake8") if n not in avail]
    print(f"Нужно минимум 2 линтера, есть {len(avail)}. Установите в ТЕКУЩЕЕ окружение:")
    print(f"    {sys.executable} -m pip install {' '.join(miss)}")
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="blindspot",
        description="Проверка, делят ли валидаторы слепые зоны (корреляция промахов по классу дефекта).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("selftest", help="прогнать selftest ядра (обязателен перед доверием)")
    s.add_argument("--n-boot", type=int, default=2000)
    s.add_argument("--seed", type=int, default=0)

    r = sub.add_parser("report", help="отчёт по готовой матрице промахов (CSV)")
    r.add_argument("csv")
    r.add_argument("--n-boot", type=int, default=2000)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--alpha", type=float, default=0.05)
    r.add_argument("--skip-selftest", action="store_true",
                   help="НЕ рекомендуется: пропустить обязательную проверку ядра перед отчётом")

    p = sub.add_parser("probe-python",
                       help="построить корпус, прогнать установленные линтеры, дать отчёт")
    p.add_argument("--out", default="blindspot_misses.csv")
    p.add_argument("--n-boot", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)

    sub.add_parser("doctor", help="проверить окружение: линтеры, Python, кодировка")

    c = sub.add_parser("candidate",
                       help="оценить нового кандидата-валидатора против уже принятого набора")
    c.add_argument("csv", help="матрица промахов, включающая столбцы кандидата и принятых")
    c.add_argument("--candidate", required=True, help="имя столбца miss_<candidate> без префикса")
    c.add_argument("--accepted", required=True,
                   help="принятый набор через запятую, напр.: pylint,ruff")
    c.add_argument("--n-boot", type=int, default=2000)
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--alpha", type=float, default=0.05)

    a = ap.parse_args(argv)
    if a.cmd == "doctor":
        sys.exit(_doctor())
    if a.cmd == "selftest":
        sys.exit(core.run_selftest(a.n_boot, a.seed))
    if a.cmd == "report":
        # ВОРОТА: ядру нельзя доверять, пока selftest не пройден
        if not a.skip_selftest:
            print("Проверка ядра (selftest) перед отчётом...")
            rc = core.run_selftest(a.n_boot, a.seed)
            if rc != 0:
                print("\nОТКАЗ: selftest ядра не пройден — отчёт не считается. "
                      "Исправьте ядро/окружение или, осознанно, используйте --skip-selftest.")
                sys.exit(rc)
            print("selftest пройден — считаю отчёт.\n")
        core.analyze_csv(a.csv, n_boot=a.n_boot, seed=a.seed, alpha=a.alpha)
    if a.cmd == "probe-python":
        probe.run(out_csv=a.out, n_boot=a.n_boot, seed=a.seed)
    if a.cmd == "candidate":
        sys.exit(_run_candidate(a))


def _run_candidate(a):
    """Инкрементальная оценка кандидата против набора по каждому классу дефекта."""
    accepted = [s.strip() for s in a.accepted.split(",") if s.strip()]
    rep = core.analyze_csv(a.csv, n_boot=a.n_boot, seed=a.seed,
                           alpha=a.alpha, verbose=False)
    any_class = False
    for z, data in rep.items():
        members = [m for m in accepted if m in data["methods"]]
        if a.candidate not in data["methods"] or not members:
            continue
        any_class = True
        ev = core.evaluate_candidate(data["res"], a.candidate, members, data["n"])
        core.print_candidate_eval(ev, z)
    if not any_class:
        print("Не нашёл кандидата или принятых в матрице. "
              "Проверьте имена столбцов miss_* в CSV.")
        return 1
    return 0


if __name__ == "__main__":
    main()
