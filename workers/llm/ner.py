"""Нейросетевые детекторы: GLiNER2 (metrika-labs/ru-pii-ner-gliner2.5) и Natasha (Slovnet NER).

Модели грузятся лениво при первом запросе; инференс не потокобезопасен, поэтому под одним lock.
"""

from __future__ import annotations

import os
import threading
from typing import Any

_GLINER_LABELS = [
    "ru_pii_person", "ru_pii_location", "ru_pii_date", "ru_pii_phone", "ru_pii_email", "ru_pii",
]

_lock = threading.Lock()
_gliner: Any = None
_natasha: Any = None


def gliner_model_name() -> str:
    return (os.getenv("GLINER_MODEL") or "").strip() or "metrika-labs/ru-pii-ner-gliner2.5"


def _threshold() -> float:
    try:
        return float(os.getenv("GLINER_THRESHOLD", "0.35"))
    except ValueError:
        return 0.35


def _chunks(text: str, size: int, overlap: int) -> list[tuple[int, str]]:
    """Окна по границам пробелов; модель принимает до 4096 токенов за раз."""
    if len(text) <= size:
        return [(0, text)]
    out: list[tuple[int, str]] = []
    pos = 0
    while pos < len(text):
        end = min(len(text), pos + size)
        if end < len(text):
            sp = text.rfind(" ", pos + size // 2, end)
            if sp > 0:
                end = sp
        out.append((pos, text[pos:end]))
        if end >= len(text):
            break
        pos = max(pos + 1, end - overlap)
    return out


def load_models() -> None:
    global _gliner, _natasha
    with _lock:
        if _gliner is None:
            import torch
            from gliner2 import AutoExtractor

            n = int(os.getenv("TORCH_THREADS", "0") or 0)
            if n > 0:
                torch.set_num_threads(n)
            _gliner = AutoExtractor.from_pretrained(gliner_model_name())
        if _natasha is None and os.getenv("USE_NATASHA", "1") != "0":
            from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter

            _natasha = (Segmenter(), NewsNERTagger(NewsEmbedding()), Doc)


def gliner_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, label) без префикса ru_pii_; «generic» — общий класс ru_pii."""
    load_models()
    size = int(os.getenv("GLINER_CHUNK_CHARS", "3000"))
    out: list[tuple[int, int, str]] = []
    with _lock:
        for off, chunk in _chunks(text, size, 200):
            res = _gliner.extract_entities(
                chunk, _GLINER_LABELS, threshold=_threshold(), include_spans=True
            )
            for label, items in (res.get("entities") or {}).items():
                short = label.removeprefix("ru_pii_") if label != "ru_pii" else "generic"
                for it in items:
                    if isinstance(it, dict) and "start" in it:
                        s, e = it["start"], it["end"]
                    else:
                        t = it["text"] if isinstance(it, dict) else str(it)
                        s = chunk.find(t)
                        if s < 0:
                            continue
                        e = s + len(t)
                    out.append((off + s, off + e, short))
    return out


def natasha_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, 'PER'|'LOC'|'ORG'); пусто, если Natasha отключена (USE_NATASHA=0)."""
    load_models()
    if _natasha is None:
        return []
    seg, tagger, Doc = _natasha
    with _lock:
        doc = Doc(text)
        doc.segment(seg)
        doc.tag_ner(tagger)
        return [(s.start, s.stop, s.type) for s in doc.spans]
