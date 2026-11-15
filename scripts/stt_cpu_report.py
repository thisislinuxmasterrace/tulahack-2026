#!/usr/bin/env python3
"""Проверка артефактов STT и сводка по группам; модели не запускаются."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import jiwer

from stt_cpu_eval import DATA, ROOT, normalize, save

sys.path.insert(0, str(ROOT / "workers" / "llm"))
from detectors import find_number_runs


def normalize_numbers(text):
    for run in reversed(find_number_runs(text)):
        text = text[:run.start] + run.digits + text[run.end:]
    return re.sub(r"(?<=\d)\s+(?=\d)", "", normalize(text))


def summarize(path, manifest):
    result = json.loads(path.read_text())
    rows = result["samples"]
    assert len({s["id"] for s in rows}) == len(rows), "duplicate sample IDs"
    selected_group = result["settings"].get("only")
    expected_ids = {key for key, sample in manifest.items() if selected_group is None or sample["group"] == selected_group}
    assert {row["id"] for row in rows} == expected_ids, "incomplete sample set"
    summaries = {}
    timing_errors = []
    for row in rows:
        def check(condition, message):
            if not condition:
                issue = dict(sample=row["id"], error=message)
                if issue not in timing_errors:
                    timing_errors.append(issue)

        source = manifest[row["id"]]
        assert row["sha256"] == source["sha256"], "manifest hash mismatch"
        assert hashlib.sha256((ROOT / row["audio"]).read_bytes()).hexdigest() == row["sha256"], "changed audio"
        assert all(math.isfinite(t) and t > 0 for t in row["times_sec"]), "invalid duration"
        assert len(row["times_sec"]) == result["settings"]["repeats"], "incomplete repeats"
        previous = -1.0
        for segment in row["segments"]:
            start, end = segment["start"], segment["end"]
            check(-0.05 <= start <= end <= row["duration_sec"] + 0.1, "segment bounds")
            check(start >= previous - 0.05, "segment order")
            previous = start
            if "tokens" in segment:
                times = segment["timestamps"]
                check(len(times) == len(segment["tokens"]), "token/timestamp count mismatch")
                check(times == sorted(times), "nonmonotonic token times")
                check(all(0 <= t <= end - start + 0.08 for t in times), "token bounds")
                # onnx-asr returns segment-relative timestamps, not absolute ones.
                check(all(start <= start + t <= row["duration_sec"] + 0.1 for t in times), "absolute token bounds")
            else:
                words = segment["words"]
                check(normalize(" ".join(w["word"] for w in words)) == normalize(segment["text"]), "word/text mismatch")
                word_previous = start
                for word in words:
                    check(start - 0.1 <= word["start"] <= word["end"] <= end + 0.1, "word bounds")
                    check(word["start"] >= word_previous - 0.05, "word order")
                    word_previous = word["start"]
        if source["text"] is not None:
            score = jiwer.process_words(normalize(source["text"]), normalize(row["text"]))
            assert abs(score.wer - row["wer"]) < 1e-12, "WER mismatch"
            assert row["word_errors"] == score.substitutions + score.deletions + score.insertions, "error count mismatch"
            assert row["reference_words"] == len(normalize(source["text"]).split()), "reference count mismatch"
        group = summaries.setdefault(row["group"], dict(samples=0, audio_sec=0.0, median_sum_sec=0.0, reference_words=0, word_errors=0, entity_hits=0, entity_count=0, number_normalized_errors=0, number_normalized_words=0))
        if source["text"] is not None:
            numeric_reference = normalize_numbers(source["text"])
            numeric_score = jiwer.process_words(numeric_reference, normalize_numbers(row["text"]))
            group["number_normalized_errors"] += numeric_score.substitutions + numeric_score.deletions + numeric_score.insertions
            group["number_normalized_words"] += len(numeric_reference.split())
        group["samples"] += 1
        group["audio_sec"] += row["duration_sec"]
        group["median_sum_sec"] += row["median_sec"]
        group["reference_words"] += row.get("reference_words", 0)
        group["word_errors"] += row.get("word_errors", 0)
        group["entity_hits"] += sum(e["found"] for e in row["entity_exact"])
        group["entity_count"] += len(row["entity_exact"])
    for group in summaries.values():
        group["rtfx"] = group["audio_sec"] / group["median_sum_sec"]
        group["wer"] = group["word_errors"] / group["reference_words"] if group["reference_words"] else None
        group["number_normalized_wer"] = group["number_normalized_errors"] / group["number_normalized_words"] if group["number_normalized_words"] else None
    return dict(name=path.stem, settings=result["settings"], peak_rss_mib=result["peak_rss_mib"], samples=len(rows), groups=summaries, structural_timing_checks="fail" if timing_errors else "pass", timing_errors=timing_errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--plot", action="store_true", help="Сохранить статический график; нужен matplotlib")
    args = parser.parse_args()
    manifest = {s["id"]: s for s in json.loads((DATA / "manifest.json").read_text())}
    results = [summarize(path, manifest) for path in args.results]
    assert all({s["id"] for s in json.loads(path.read_text())["samples"]} == {s["id"] for s in json.loads(args.results[0].read_text())["samples"]} for path in args.results), "different sample sets"
    save(DATA / "summary.json", results)
    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels = ["GigaAM CTC INT8" if r["settings"]["engine"] == "gigaam" else f"Whisper small · beam {r['settings']['beam']}" for r in results]
        metrics = [
            ("Два полных разговора: 322,85 с аудио", "Время распознавания, с · меньше лучше", [r["groups"]["conversation"]["median_sum_sec"] for r in results], "с"),
            ("24 телефонных фрагмента: 171 эталонное слово", "WER, % · вставки могут дать больше 100%", [r["groups"]["phone"]["wer"] * 100 for r in results], "%"),
            ("Пиковая память процесса за весь прогон", "RSS, MiB · меньше лучше", [r["peak_rss_mib"] for r in results], "MiB"),
        ]
        fig, axes = plt.subplots(3, 1, figsize=(8, 6.9), layout="constrained")
        for axis, (title, xlabel, values, unit) in zip(axes, metrics):
            bars = axis.barh(labels, values, color=["#18766d", "#527da8", "#9d6729"][:len(results)], height=0.55)
            axis.invert_yaxis()
            axis.set_title(title, loc="left", fontsize=11)
            axis.set_xlabel(xlabel, fontsize=9)
            axis.set_xlim(0, max(values) * 1.3)
            axis.spines[["top", "right", "left"]].set_visible(False)
            axis.tick_params(axis="both", labelsize=9)
            axis.bar_label(bars, labels=[f"{value:.2f} {unit}" for value in values], padding=5, fontsize=9)
        fig.savefig(DATA / "stt-cpu-comparison.png", dpi=150)
        plt.close(fig)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
