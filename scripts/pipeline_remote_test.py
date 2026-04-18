#!/usr/bin/env python3
"""
Полный прогон: STT → LLM (/v1/anonymize) → redact (/v1/redact) на удалённых воркерах.
Пишет артефакты в --out-dir и печатает время каждого запроса.

Пример:
  pip install requests
  python scripts/pipeline_remote_test.py \\
    --host 127.0.0.1 \\
    --token YOUR_WORKER_TOKEN \\
    --audio pipeline_test_results/test.mp3 \\
    --out-dir pipeline_test_results/run_test

Переменные окружения (если не заданы флаги):
  PIPELINE_HOST (по умолчанию 127.0.0.1), WORKER_TOKEN
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Remote pipeline: STT → LLM → redact + timings")
    p.add_argument(
        "--host",
        default=os.getenv("PIPELINE_HOST", "127.0.0.1"),
        help="хост воркеров (без http://); по умолчанию 127.0.0.1",
    )
    p.add_argument(
        "--token",
        default=os.getenv("WORKER_TOKEN", "").strip(),
        help="Bearer-токен (WORKER_TOKEN); пусто — без заголовка",
    )
    p.add_argument(
        "--audio",
        default="pipeline_test_results/test.mp3",
        help="входной аудиофайл для STT",
    )
    p.add_argument(
        "--out-dir",
        default="pipeline_test_results/run_test",
        help="каталог для stt-out.json, llm-out.json, redacted.mp3",
    )
    p.add_argument("--stt-port", type=int, default=8001)
    p.add_argument("--llm-port", type=int, default=8081)
    p.add_argument("--redact-port", type=int, default=8082)
    p.add_argument("--max-time", type=int, default=900, help="таймаут curl/requests, сек")
    args = p.parse_args()

    audio = Path(args.audio)
    if not audio.is_file():
        print(f"audio not found: {audio}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stt_path = out_dir / "stt-out.json"
    llm_path = out_dir / "llm-out.json"
    red_path = out_dir / "redacted.mp3"

    host = args.host.strip().rstrip("/")
    token = (args.token or "").strip()
    auth: list[str] = []
    if token:
        auth = ["-H", f"Authorization: Bearer {token}"]

    curl_fmt = (
        "HTTP %{http_code} | total %{time_total}s | connect %{time_connect}s | "
        "TTFB %{time_starttransfer}s\\n"
    )

    # --- STT ---
    stt_url = f"http://{host}:{args.stt_port}/v1/transcribe"
    print(f"=== STT {stt_url} ===")
    cmd_stt = [
        "curl",
        "-sS",
        "--max-time",
        str(args.max_time),
        "-X",
        "POST",
        stt_url,
        *auth,
        "-F",
        f"file=@{audio.resolve()}",
        "-o",
        str(stt_path.resolve()),
        "-w",
        curl_fmt,
    ]
    r_stt = subprocess.run(cmd_stt, capture_output=True, text=True)
    sys.stdout.write(r_stt.stdout)
    if r_stt.returncode != 0:
        print(r_stt.stderr, file=sys.stderr)
        return r_stt.returncode or 1
    if not stt_path.is_file() or stt_path.stat().st_size == 0:
        print("STT: empty output", file=sys.stderr)
        return 1

    # --- LLM ---
    llm_url = f"http://{host}:{args.llm_port}/v1/anonymize"
    print(f"=== LLM {llm_url} ===")
    cmd_llm = [
        "curl",
        "-sS",
        "--max-time",
        str(args.max_time),
        "-X",
        "POST",
        llm_url,
        *auth,
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        f"@{stt_path.resolve()}",
        "-o",
        str(llm_path.resolve()),
        "-w",
        curl_fmt,
    ]
    r_llm = subprocess.run(cmd_llm, capture_output=True, text=True)
    sys.stdout.write(r_llm.stdout)
    if r_llm.returncode != 0:
        print(r_llm.stderr, file=sys.stderr)
        return r_llm.returncode or 1

    try:
        llm_obj = json.loads(llm_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"LLM: invalid JSON: {e}", file=sys.stderr)
        return 1

    for e in llm_obj.get("llm_entities") or []:
        if isinstance(e, dict):
            print(
                " ",
                e.get("entity_type"),
                e.get("start_ms"),
                e.get("end_ms"),
            )

    # --- Redact ---
    try:
        import requests
    except ImportError:
        print("pip install requests", file=sys.stderr)
        return 1

    red_url = f"http://{host}:{args.redact_port}/v1/redact"
    print(f"=== Redact {red_url} ===")
    report_str = json.dumps(llm_obj, ensure_ascii=False)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    t0 = time.perf_counter()
    with open(audio, "rb") as audio_f:
        r = requests.post(
            red_url,
            headers=headers,
            files={"file": (audio.name, audio_f)},
            data={"report": report_str},
            timeout=args.max_time,
        )
    elapsed = time.perf_counter() - t0
    print(f"HTTP {r.status_code} | wall {elapsed:.3f}s (full request)")
    if r.status_code != 200:
        print(r.text[:4000], file=sys.stderr)
        return 1
    red_path.write_bytes(r.content)
    print(f"saved {red_path} bytes {len(r.content)}")

    print("=== done ===")
    for path in (stt_path, llm_path, red_path):
        sz = path.stat().st_size if path.is_file() else 0
        print(f"  {path}  ({sz} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
