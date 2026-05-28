# -*- coding: utf-8 -*-
"""
core.py — измерительное ядро: корреляция промахов пары проверок по классу дефекта Z.

ЧТО ДЕЛАЕТ:
  Берёт CSV промахов и внутри КАЖДОГО класса дефекта Z считает три метрики
  (не пуля по Z — пулинг даёт ложную корреляцию, Симпсон):
    (1) попарная корреляция промахов методов (phi);
    (2) joint-miss vs произведение маргиналов (во сколько раз совместный промах
        чаще, чем при независимости);
    (3) total correlation / multi-information (информационный аналог
        «совместная картина ошибок раскладывается в произведение независимых»).
  Каждая метрика идёт с SHUFFLE-контролем (убивает межметодную зависимость,
  сохраняя маргиналы → оценивает конечновыборочное смещение) и bootstrap-ДИ.

ФОРМАТ CSV:
  task_id, defect_class, ground_truth_defect, miss_<метод1>, miss_<метод2>, ...
  miss_* ∈ {0,1}, 1 = метод ПРОПУСТИЛ настоящий дефект (false-negative).
  Для анализа берутся только строки с ground_truth_defect == 1.

ВЕРДИКТ (зафиксирован до прогона):
  Независимость по Z только если ОДНОВРЕМЕННО: попарн. corr ≈ 0 (ДИ включает 0)
  И joint ≈ произведение (ratio-ДИ включает 1) И debiased TC ≈ 0 (ДИ включает 0).
  Иначе — методы условно зависимы по Z (делят общее слепое пятно).

ЗАПУСК (через CLI пакета):
  blindspot selftest
  blindspot report misses.csv
  blindspot report misses.csv --n-boot 2000 --seed 0
"""
import argparse
import sys
import numpy as np

# ───────────────────────────── базовые статистики ─────────────────────────────

def _phi_corr(x, y):
    """Корреляция двух бинарных векторов (phi = Pearson на {0,1})."""
    if x.std() == 0 or y.std() == 0:
        return np.nan          # нулевая дисперсия → корреляция не определена
    return float(np.corrcoef(x, y)[0, 1])


def _binary_entropy_bits(col):
    """H(m_i) в битах для бинарного столбца."""
    p = col.mean()
    return _entropy_from_probs(np.array([1 - p, p]))


def _entropy_from_probs(p):
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def _joint_entropy_bits(M):
    """H(m_1,...,m_k) по наблюдаемым паттернам столбцов M [n,k]."""
    n = M.shape[0]
    # код паттерна как целое
    weights = (1 << np.arange(M.shape[1]))
    codes = (M * weights).sum(axis=1)
    _, counts = np.unique(codes, return_counts=True)
    return _entropy_from_probs(counts / n)


def total_correlation_bits(M):
    """TC = Σ H(m_i) − H(joint). TC=0 ⇔ полная независимость ⇔ тензор rank-1."""
    sum_marg = sum(_binary_entropy_bits(M[:, i]) for i in range(M.shape[1]))
    return sum_marg - _joint_entropy_bits(M)


def joint_vs_product(M):
    """P(все пропустили) и Π P(каждый пропустил); ratio = joint/product."""
    joint = float((M.sum(axis=1) == M.shape[1]).mean())
    product = float(np.prod(M.mean(axis=0)))
    ratio = joint / product if product > 0 else np.nan
    return joint, product, ratio


def _shuffle_independent(M, rng):
    """Перемешать каждый столбец независимо → убить межметодную связь,
    сохранить маргиналы. Оценивает конечновыборочный пол метрик."""
    out = M.copy()
    for i in range(out.shape[1]):
        out[:, i] = rng.permutation(out[:, i])
    return out


# ───────────────────────────── bootstrap-обёртка ──────────────────────────────

def _bootstrap_ci(M, stat_fn, n_boot, rng, alpha=0.05):
    """Перцентильный ДИ статистики stat_fn(M) по ресэмплу строк."""
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


# ───────────────────────────── анализ одного Z ────────────────────────────────

def analyze_class(M, methods, n_boot, rng, alpha=0.05):
    """Все метрики внутри одного класса Z. M [n,k] бинарная, k=len(methods)."""
    n = M.shape[0]
    res = {"n": n, "marginal_miss": {m: float(M[:, i].mean())
                                     for i, m in enumerate(methods)}}

    # (1) попарные корреляции + shuffle
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

    # (2) joint-miss vs произведение (все методы)
    joint, product, ratio = joint_vs_product(M)
    ratio_ci = _bootstrap_ci(M, lambda A: joint_vs_product(A)[2], n_boot, rng, alpha)
    res["joint_vs_product"] = {"joint": joint, "product": product,
                               "ratio": ratio, "ratio_ci": ratio_ci}

    # (3) total correlation, debiased по shuffle
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
    """Правило вердикта, зафиксированное до прогона."""
    # corr: все ДИ включают 0?
    corr_ok = all((p["corr_ci"][0] <= 0 <= p["corr_ci"][1])
                  for p in res["pairwise"].values()
                  if not np.isnan(p["corr_ci"][0]))
    # ratio: ДИ включает 1?
    rci = res["joint_vs_product"]["ratio_ci"]
    ratio_ok = (not np.isnan(rci[0])) and (rci[0] <= 1 <= rci[1])
    # TC: ДИ включает 0?
    tci = res["total_correlation"]["tc_debiased_ci"]
    tc_ok = (not np.isnan(tci[0])) and (tci[0] <= 0 <= tci[1])
    independent = corr_ok and ratio_ok and tc_ok
    return {"independent": independent,
            "corr_ok": corr_ok, "ratio_ok": ratio_ok, "tc_ok": tc_ok}


def evaluate_candidate(res, candidate, accepted, n, ci_width_max=0.6):
    """Инкрементально: стоит ли добавлять candidate к уже принятому набору accepted?

    Берёт уже посчитанный res['pairwise'] и смотрит корреляцию промахов кандидата
    с КАЖДЫМ принятым валидатором. Вердикт по тому же порогу, что и ранжирование:
      - 'duplicate'   : есть принятый, с которым ДИ corr строго > 0.8 (дубль)
      - 'complements' : со всеми принятыми ДИ corr накрывает 0 (дополняет всех)
      - 'weak'        : частичное перекрытие хотя бы с одним
      - 'inconclusive': мало данных / широкий ДИ — НЕ доверять выводу

    Возвращает dict с вердиктом и разбором по парам. inconclusive имеет приоритет:
    на малой выборке нельзя объявлять, что кандидат дополняет набор.
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
    """Человекочитаемый вывод evaluate_candidate."""
    v = ev["verdict"]
    cand = ev["candidate"]
    print(f"\n-- кандидат '{cand}' против набора {ev['accepted']} (класс {z}) --")
    for m, corr, rel in ev["per_member"]:
        cc = "n/a" if corr != corr else f"{corr:+.2f}"
        print(f"    vs {m}: corr={cc}  ({rel})")
    if v == "inconclusive":
        print(f"  ВЕРДИКТ: НЕОПРЕДЕЛЁННО — мало данных. Расширьте корпус, "
              f"не делайте вывод о кандидате сейчас.")
    elif v == "duplicate":
        print(f"  ВЕРДИКТ: ДУБЛИРУЕТ {ev['dup_with']} — добавлять не стоит, "
              f"покрытие по {z} не вырастет.")
    elif v == "weak":
        print(f"  ВЕРДИКТ: частично перекрывается с {ev['weak_with']} — "
              f"добавляет немного; решайте по цене лишней проверки в CI.")
    else:
        print(f"  ВЕРДИКТ: ДОПОЛНЯЕТ набор — независим со всеми принятыми, "
              f"стоит включить в стек по {z}.")
    return v



def _print_class(res):
    mm = ", ".join(f"{k}={v:.2f}" for k, v in res["marginal_miss"].items())
    print(f"  маргин. промах: {mm}")
    for pair, p in res["pairwise"].items():
        c = p["corr"]
        cs = "nan" if np.isnan(c) else f"{c:+.3f}"
        ci = p["corr_ci"]
        ci_s = "—" if np.isnan(ci[0]) else f"[{ci[0]:+.3f},{ci[1]:+.3f}]"
        print(f"    corr {pair}: {cs} ДИ{ci_s} (shuffle≈{p['shuffle_corr']:+.3f})"
              if not np.isnan(p["shuffle_corr"]) else
              f"    corr {pair}: {cs} ДИ{ci_s}")
    jp = res["joint_vs_product"]
    rci = jp["ratio_ci"]
    rci_s = "—" if np.isnan(rci[0]) else f"[{rci[0]:.2f},{rci[1]:.2f}]"
    print(f"    joint={jp['joint']:.4f} product={jp['product']:.4f} "
          f"ratio={jp['ratio']:.2f} ДИ{rci_s}")
    tc = res["total_correlation"]
    tci = tc["tc_debiased_ci"]
    tci_s = "—" if np.isnan(tci[0]) else f"[{tci[0]:+.3f},{tci[1]:+.3f}]"
    print(f"    TC debiased={tc['tc_debiased_bits']:+.3f} бит ДИ{tci_s} "
          f"(obs={tc['tc_obs_bits']:.3f}, shuffle={tc['tc_shuffle_bits']:.3f})")




# ───────────────────────────── загрузка матрицы промахов ──────────────────────

def load_misses(csv_path):
    """Читает CSV (task_id, defect_class, ground_truth_defect, miss_<m>...).
    Возвращает (data: {z: ndarray[n,k]}, methods: list[str], notes: list[str]).
    Пустые поля = недоступный валидатор: метод без данных исключается,
    строки с частичными пропусками отбрасываются."""
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split(",")
        for line in f:
            if line.strip():
                rows.append(line.rstrip("\n").split(","))
    col = {name: i for i, name in enumerate(header)}
    for need in ("defect_class", "ground_truth_defect"):
        if need not in col:
            raise ValueError(f"в CSV нет колонки {need}")
    methods = [h[len("miss_"):] for h in header if h.startswith("miss_")]
    if len(methods) < 2:
        raise ValueError("нужно >=2 колонок miss_<метод>")
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
        notes.append(f"исключены методы без данных: {', '.join(dropped)}")
    methods = [methods[i] for i in keep]
    if len(methods) < 2:
        raise ValueError("после отсева <2 методов с данными")
    data, skipped = {}, 0
    for z, lst in raw_data.items():
        for vals in lst:
            sub = [vals[i] for i in keep]
            if "" in sub:
                skipped += 1
                continue
            data.setdefault(z, []).append([int(v) for v in sub])
    if skipped:
        notes.append(f"пропущено строк с неполными данными: {skipped}")
    return {z: __import__("numpy").array(v, dtype=int) for z, v in data.items()}, methods, notes


def analyze_csv(csv_path, n_boot=2000, seed=0, alpha=0.05, verbose=True):
    """Анализ независимости по каждому Z. Возвращает {z: {'res':..,'verdict':..,'n':..}}."""
    import numpy as np
    rng = np.random.default_rng(seed)
    data, methods, notes = load_misses(csv_path)
    if verbose:
        print("=" * 70)
        print("BLINDSPOT — корреляция промахов валидаторов по классу дефекта Z")
        print("=" * 70)
        for nt in notes:
            print(f"  ! {nt}")
        print(f"Методы: {', '.join(methods)}")
        print(f"Классов Z: {len(data)} | bootstrap={n_boot}, seed={seed}\n")
    out = {}
    for z, M in sorted(data.items()):
        n = M.shape[0]
        if verbose:
            print(f"-- Z = {z}  (n={n}) " + "-" * 30)
            if n < 10:
                print("  ! n<10 — выборка мала, ДИ НЕ интерпретируемы как 'независимы'.")
        res = analyze_class(M, methods, n_boot, rng, alpha)
        v = verdict_for_class(res, alpha)
        # доля совместных промахов в корпусе — определяет величину φ
        both_miss = float((M.sum(axis=1) == M.shape[1]).mean())
        # ширина ДИ корреляции (по парам) — для вердикта INCONCLUSIVE
        ci_widths = [p["corr_ci"][1] - p["corr_ci"][0]
                     for p in res["pairwise"].values()
                     if p["corr_ci"][0] == p["corr_ci"][0]]  # без nan
        max_ci_width = max(ci_widths) if ci_widths else float("nan")
        inconclusive = (n < 10) or (max_ci_width == max_ci_width and max_ci_width > 0.6)
        if verbose:
            _print_class(res)
            if inconclusive:
                tag = "НЕОПРЕДЕЛЁННО — мало данных (расширьте корпус)"
            elif v["independent"]:
                tag = "НЕЗАВИСИМЫ"
            else:
                tag = "ЗАВИСИМЫ"
            print(f"  ВЕРДИКТ Z={z}: {tag}  "
                  f"[corr_ok={v['corr_ok']} ratio_ok={v['ratio_ok']} tc_ok={v['tc_ok']}]")
            # защита от ошибки «φ как факт»: φ управляется составом корпуса
            print(f"  ! доля совместных промахов в корпусе = {both_miss:.0%}. "
                  f"Если она не отражает ваш реальный код, абсолютное φ непереносимо —")
            print(f"    переносим только КАЧЕСТВЕННЫЙ вывод (независимы / перекрываются / дубликаты).\n")
        v["inconclusive"] = bool(inconclusive)
        v["both_miss_frac"] = both_miss
        out[z] = {"res": res, "verdict": v, "n": int(n), "methods": methods}
    if verbose:
        print("Статус: [ЧИСЛЕННО] при честных контролях, НЕ [ДОКАЗАНО]. "
              "Чистота ground truth — на вас (см. README).")
    return out



def make_independent(n, marginals, rng):
    """Каждый метод промахивается независимо со своей вероятностью."""
    return np.column_stack([rng.random(n) < p for p in marginals]).astype(int)


def make_dependent(n, base, hard_frac, rng):
    """Общий латентный фактор «трудный дефект»: с долей hard_frac ВСЕ методы
    промахиваются вместе; иначе — независимо с базовой вероятностью base.
    Это даёт сильную положительную связь промахов."""
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
    print("SELFTEST ИНСТРУМЕНТА (синтетика; инструмент обязан и пройти, и провалить)")
    print("=" * 70)

    # A. заведомо НЕЗАВИСИМЫЕ
    print("\n--- A. заведомо НЕЗАВИСИМЫЕ промахи (marginals 0.3/0.4/0.5/0.35) ---")
    Ma = make_independent(n, [0.30, 0.40, 0.50, 0.35], rng)
    ra = analyze_class(Ma, methods, n_boot, rng)
    _print_class(ra)
    va = verdict_for_class(ra)
    print(f"  → вердикт: {'НЕЗАВИСИМЫ' if va['independent'] else 'ЗАВИСИМЫ'} "
          f"(ожидание: НЕЗАВИСИМЫ)")

    # B. заведомо ЗАВИСИМЫЕ
    print("\n--- B. заведомо ЗАВИСИМЫЕ промахи (общий 'трудный дефект', frac=0.35) ---")
    Mb = make_dependent(n, [0.15, 0.15, 0.15, 0.15], 0.35, rng)
    rb = analyze_class(Mb, methods, n_boot, rng)
    _print_class(rb)
    vb = verdict_for_class(rb)
    print(f"  → вердикт: {'НЕЗАВИСИМЫ' if vb['independent'] else 'ЗАВИСИМЫ'} "
          f"(ожидание: ЗАВИСИМЫ)")

    # Итог: инструмент должен различить A и B
    ok = va["independent"] and (not vb["independent"])
    print("\n" + "=" * 70)
    if ok:
        print("SELFTEST ПРОЙДЕН: инструмент отличает независимый случай от зависимого.")
        print("  (A→НЕЗАВИСИМЫ, B→ЗАВИСИМЫ — как требуется)")
    else:
        print("SELFTEST ПРОВАЛЕН: инструмент НЕ различает A и B → НЕ пускать на данные.")
        print(f"  A independent={va['independent']} (ждали True), "
              f"B independent={vb['independent']} (ждали False)")
    print("=" * 70)
    return 0 if ok else 1


