"""Детекция ПДн: GLiNER2 + Natasha + правила -> список Span."""

from __future__ import annotations

import os

from detectors import (
    Span,
    build_addresses,
    detect_email,
    detect_numeric,
    find_number_runs,
    merge_spans,
)
from ner import gliner_spans, natasha_spans

DEFAULT_TYPES = "passport,inn,snils,phone,email,address"


def enabled_types() -> frozenset[str]:
    raw = os.getenv("ENTITY_TYPES") or DEFAULT_TYPES
    return frozenset(t.strip() for t in raw.split(",") if t.strip())


def detect(text: str) -> list[Span]:
    types = enabled_types()
    spans: list[Span] = detect_numeric(text) + detect_email(text)
    atoms: list[tuple[int, int]] = []

    # Числа (паспорт/ИНН/СНИЛС/телефон по контексту) уже найдены правилами по всему тексту; от GLiNER берём
    # границы телефона (сужаем до самой длинной числовой группы внутри спана), e-mail, локации и имена.
    for s, e, label in gliner_spans(text):
        sub = text[s:e]
        if label == "phone":
            runs = find_number_runs(sub)
            best = max(runs, key=lambda r: len(r.digits), default=None)
            if best and len(best.digits) >= 7:
                spans.append(Span(s + best.start, s + best.end, "phone"))
        elif label == "email":
            spans.append(Span(s, e, "email"))
        elif label == "location":
            atoms.append((s, e))
        elif label == "person":
            spans.append(Span(s, e, "person"))

    for s, e, label in natasha_spans(text):
        if label == "LOC":
            atoms.append((s, e))
        elif label == "PER":
            spans.append(Span(s, e, "person"))

    spans += build_addresses(text, atoms)
    return [sp for sp in merge_spans(spans) if sp.type in types]
