"""Прогон detect() на tests/samples.json: покрытие эталонных фрагментов и совпадение типа.

Запуск из workers/llm:  python tests/run_samples.py [-v]
Типы эталона policy/card в контракте отсутствуют — для них проверяется только покрытие.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import detect  # noqa: E402

CONTRACT = {"passport", "inn", "snils", "phone", "email", "address", "person"}
verbose = "-v" in sys.argv
data = json.load(open(Path(__file__).with_name("samples.json"), encoding="utf-8"))
detect("прогрев")
tot = hit = typ_ok = n_fp = 0
t_all = 0.0
for d in data:
    text = d["text"]
    t = time.time(); spans = detect(text); dt = time.time() - t; t_all += dt
    cov = [False] * len(text); kind = [None] * len(text)
    for sp in spans:
        for i in range(sp.start, sp.end):
            cov[i] = True; kind[i] = sp.type
    gold_chars = set()
    print(f"== {d['id']} ({dt:.2f}s)")
    for g, gt in d["gold"]:
        s = text.find(g); gold_chars.update(range(s, s + len(g)))
        frac = sum(cov[s:s + len(g)]) / len(g)
        kinds = {kind[i] for i in range(s, s + len(g)) if kind[i]}
        ok_t = gt in kinds or gt not in CONTRACT
        tot += 1; hit += frac >= 0.9; typ_ok += (frac >= 0.9 and ok_t)
        if verbose or frac < 0.9 or not ok_t:
            print(f"   {'OK  ' if frac >= 0.9 else 'MISS'} {gt:9} cov={frac:.2f} types={sorted(kinds)} {g!r}")
    for sp in spans:
        if not any(i in gold_chars for i in range(sp.start, sp.end)):
            n_fp += 1; print(f"   FALSE-POS {sp.type}: {text[sp.start:sp.end]!r}")
print(f"\nпокрытие>=90%: {hit}/{tot}, +верный тип: {typ_ok}/{tot}, ложных спанов: {n_fp}, время детекции: {t_all:.2f}s")
