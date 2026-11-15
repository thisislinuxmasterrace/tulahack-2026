#!/usr/bin/env python3
"""Локальное сравнение CPU STT. Аудио и модели хранятся в .stt-eval/."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.metadata
import json
import os
import re
import resource
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".stt-eval"
GIGA_REV = "322c3b29492673eb7d0b434bfa9dfb8653e34d02"
VOICE_REV = "6b9cfaacb4fb2e02a9621227e3c1a48bec9710c3"
WHISPER_REV = "536b0662742c02347bc0e980a01041f333bce120"


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def fetch(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response:
            content = response.read()
        path.write_bytes(content)


def normalize(text):
    return " ".join(re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е")))


def calls():
    import soundfile as sf
    samples = json.loads((DATA / "manifest.json").read_text())
    samples = [s for s in samples if s["group"] not in ("phone", "conversation")]
    for offset in (0, 3000, 6000):
        query = urllib.parse.urlencode(dict(dataset="Joarnixon/open-stt-calls", config="default", split="train", offset=offset, length=8))
        with urllib.request.urlopen("https://datasets-server.huggingface.co/rows?" + query, timeout=120) as response:
            rows = json.load(response)["rows"]
        for item in rows:
            row = item["row"]
            name = f"openstt-{item['row_idx']}"
            source = DATA / "audio" / f"{name}-source.wav"
            target = DATA / "audio" / f"{name}.wav"
            fetch(row["audio"][0]["src"], source)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ar", "16000", "-ac", "1", str(target)], check=True)
            samples.append(dict(id=name, group="phone", audio=str(target.relative_to(ROOT)), text=row["sentence"], source=row["path"], duration_sec=sf.info(target).duration, sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    repo = "https://huggingface.co/datasets/datahiveai/russian-conversations-sample/resolve/1d22534f5a9ef4a377bc42faeb456d456ce29850/preview/"
    metadata = DATA / "datahive-metadata.jsonl"
    fetch(repo + "metadata.jsonl", metadata)
    conversations = sorted((json.loads(line) for line in metadata.read_text().splitlines()), key=lambda row: row["duration_seconds"])[:2]
    for row in conversations:
        source = DATA / "audio" / row["file_name"]
        target = source.with_suffix(".wav")
        fetch(repo + row["file_name"], source)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ar", "16000", "-ac", "1", str(target)], check=True)
        samples.append(dict(id=source.stem, group="conversation", audio=str(target.relative_to(ROOT)), text=None, source=repo + row["file_name"], duration_sec=sf.info(target).duration, sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    save(DATA / "manifest.json", samples)
    print(f"Prepared {len(samples)} samples, {sum(s['duration_sec'] for s in samples):.1f}s", flush=True)


def prepare():
    import numpy as np
    import soundfile as sf
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice

    DATA.mkdir(exist_ok=True)
    # Separate offsets avoid evaluating only consecutive sentences from one book.
    samples = []
    for offset in (0, 500, 1000, 1500):
        query = urllib.parse.urlencode(dict(dataset="istupakov/russian_librispeech", config="default", split="test", offset=offset, length=4))
        with urllib.request.urlopen("https://datasets-server.huggingface.co/rows?" + query, timeout=120) as response:
            rows = json.load(response)["rows"]
        for item in rows:
            row = item["row"]
            name = f"ruls-{item['row_idx']}"
            source = DATA / "audio" / f"{name}-source.wav"
            target = DATA / "audio" / f"{name}.wav"
            fetch(row["audio"][0]["src"], source)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ar", "16000", "-ac", "1", str(target)], check=True)
            samples.append(dict(id=name, group="human", audio=str(target.relative_to(ROOT)), text=row["text"], source=row["audio_filepath"]))

    prefix = "ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx"
    voice_path = hf_hub_download("rhasspy/piper-voices", prefix, revision=VOICE_REV)
    hf_hub_download("rhasspy/piper-voices", prefix + ".json", revision=VOICE_REV)
    voice = PiperVoice.load(voice_path)
    cases = [
        ("person", "Здравствуйте. Меня зовут Сергей Николаевич Ковалёв. Я звоню по поводу моей заявки.", ["Сергей Николаевич Ковалёв"]),
        ("address", "Новый адрес доставки: город Тула, улица Октябрьская, дом четырнадцать, квартира пятьдесят два.", ["Тула", "улица Октябрьская", "четырнадцать", "пятьдесят два"]),
        ("digits", "Записывайте паспорт: четыре пять один ноль, один два три четыре пять шесть. Телефон: восемь девять один шесть пять пять пять один два три четыре.", ["четыре пять один ноль", "один два три четыре пять шесть", "восемь девять один шесть пять пять пять один два три четыре"]),
        ("email", "Моя почта: анна точка ершова собака яндекс точка ру. Фамилия Ершова, имя Анна, отчество Павловна.", ["анна точка ершова собака яндекс точка ру", "Ершова", "Анна", "Павловна"]),
    ]
    for name, text, entities in cases:
        audio = np.concatenate([chunk.audio_float_array for chunk in voice.synthesize(text)])
        source = DATA / "audio" / f"pii-{name}-source.wav"
        target = DATA / "audio" / f"pii-{name}.wav"
        sf.write(source, audio, voice.config.sample_rate)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ar", "16000", "-ac", "1", str(target)], check=True)
        samples.append(dict(id=f"pii-{name}", group="synthetic", audio=str(target.relative_to(ROOT)), text=text, entities=entities))
    # Concatenation checks long-form VAD and preservation of offsets after silence.
    pieces, references, spans = [], [], []
    cursor = 0
    for sample in samples[-4:]:
        audio, sr = sf.read(ROOT / sample["audio"], dtype="float32")
        spans.append(dict(id=sample["id"], start=cursor / sr, end=(cursor + len(audio)) / sr))
        pieces.extend((audio, np.zeros(sr * 2, dtype="float32")))
        cursor += len(audio) + sr * 2
        references.append(sample["text"])
    target = DATA / "audio" / "pii-long.wav"
    sf.write(target, np.concatenate(pieces), 16000)
    samples.append(dict(id="pii-long", group="synthetic-long", audio=str(target.relative_to(ROOT)), text=" ".join(references), source_spans=spans))
    for sample in samples:
        path = ROOT / sample["audio"]
        sample["duration_sec"] = sf.info(path).duration
        sample["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(DATA / "manifest.json", samples)
    print(f"Prepared {len(samples)} samples, {sum(s['duration_sec'] for s in samples):.1f}s", flush=True)


def run(args):
    import jiwer
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    samples = json.loads((DATA / "manifest.json").read_text())
    started = time.perf_counter()
    if args.engine == "whisper":
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        from huggingface_hub import snapshot_download
        local = snapshot_download("Systran/faster-whisper-small", revision=WHISPER_REV, allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"], local_dir=str(DATA / "models" / "small"))
        base = WhisperModel(local, device="cpu", compute_type="int8", cpu_threads=args.threads, num_workers=1)
        model = base if args.unbatched else BatchedInferencePipeline(base)

        def recognize(path):
            batching = {} if args.unbatched else {"batch_size": args.batch}
            segments, _ = model.transcribe(str(path), language="ru", beam_size=args.beam, word_timestamps=True, vad_filter=True, vad_parameters={"min_silence_duration_ms": 500}, **batching)
            result = [dict(start=s.start, end=s.end, text=s.text, words=[dict(word=w.word, start=w.start, end=w.end, probability=w.probability) for w in s.words or []]) for s in segments]
            return dict(text=" ".join(s["text"].strip() for s in result), segments=result)
    else:
        import onnx_asr
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = args.threads
        options.inter_op_num_threads = 1
        from huggingface_hub import snapshot_download
        suffix = ".int8" if args.precision == "int8" else ""
        local = snapshot_download("istupakov/gigaam-v3-onnx", revision=GIGA_REV, allow_patterns=["config.json", "v3_vocab.txt", f"v3_ctc{suffix}.onnx"], local_dir=str(DATA / "models" / f"gigaam-{args.precision}"))
        model = onnx_asr.load_model("gigaam-v3-ctc", path=local, quantization=args.precision if args.precision == "int8" else None, sess_options=options, providers=["CPUExecutionProvider"])
        vad = onnx_asr.load_vad("silero", sess_options=options, providers=["CPUExecutionProvider"])
        model = model.with_vad(vad, batch_size=args.batch, max_speech_duration_s=20, min_silence_duration_ms=500).with_timestamps()

        def recognize(path):
            result = [dataclasses.asdict(s) for s in model.recognize(str(path))]
            return dict(text=" ".join(s["text"] for s in result), segments=result)

    load_seconds = time.perf_counter() - started
    recognize(ROOT / samples[0]["audio"])
    output = dict(settings=vars(args), load_sec_including_download=load_seconds, versions={p: importlib.metadata.version(p) for p in ("faster-whisper", "ctranslate2", "av", "onnx-asr", "onnxruntime", "numpy", "jiwer")}, samples=[])
    for sample in samples:
        if args.only and sample["group"] != args.only:
            continue
        times = []
        for _ in range(args.repeats):
            t0 = time.perf_counter()
            prediction = recognize(ROOT / sample["audio"])
            times.append(time.perf_counter() - t0)
        hypothesis = normalize(prediction["text"])
        row = {**sample, "reference": sample["text"], **prediction, "times_sec": times, "median_sec": statistics.median(times)}
        if sample["text"] is not None:
            reference = normalize(sample["text"])
            score = jiwer.process_words(reference, hypothesis)
            row.update(wer=score.wer, word_errors=score.substitutions + score.deletions + score.insertions, reference_words=len(reference.split()))
        row["entity_exact"] = [{"text": e, "found": f" {normalize(e)} " in f" {hypothesis} "} for e in sample.get("entities", [])]
        output["samples"].append(row)
        output["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        save(DATA / "results" / f"{args.name}.json", output)
        print(f"{args.name} {sample['id']}: {row['median_sec']:.3f}s / {sample['duration_sec']:.2f}s, WER {row.get('wer')}", flush=True)
    for group in sorted({s["group"] for s in output["samples"]}):
        rows = [s for s in output["samples"] if s["group"] == group]
        elapsed = sum(s["median_sec"] for s in rows)
        words = sum(s.get("reference_words", 0) for s in rows)
        print(json.dumps(dict(group=group, audio_sec=sum(s["duration_sec"] for s in rows), elapsed_sec=elapsed, wer=sum(s.get("word_errors", 0) for s in rows) / words if words else None, peak_rss_mib=output["peak_rss_mib"])), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "calls", "run"])
    parser.add_argument("--engine", choices=["whisper", "gigaam"], default="whisper")
    parser.add_argument("--name", default="whisper-small-b1")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--beam", type=int, default=1)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--precision", choices=["fp32", "int8"], default="int8")
    parser.add_argument("--unbatched", action="store_true", help="Диагностика обычного WhisperModel вместо BatchedInferencePipeline")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--only", choices=["human", "synthetic", "synthetic-long", "phone", "conversation"])
    parsed = parser.parse_args()
    if parsed.repeats < 1 or parsed.threads < 1 or parsed.batch < 1 or parsed.beam < 1:
        parser.error("repeats, threads, batch and beam must be positive")
    {"prepare": prepare, "calls": calls, "run": lambda: run(parsed)}[parsed.action]()
