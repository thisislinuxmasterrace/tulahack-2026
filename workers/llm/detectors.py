"""Правила поверх NER: числа словами, ИНН/СНИЛС/паспорт/телефон по контексту, e-mail «собака/точка», сборка адресов.

Модуль без ML-зависимостей: принимает «атомы» от нейросетей (GLiNER, Natasha) и сырой текст.
Все спаны — полуинтервалы [start, end) в символах исходной строки.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Приоритет при пересечении спанов разных типов (меньше — важнее).
TYPE_PRIORITY = {"passport": 0, "snils": 1, "inn": 2, "email": 3, "phone": 4, "address": 5, "person": 6}


@dataclass
class Span:
    start: int
    end: int
    type: str


# ---------- числа словами ----------

_UNITS = {
    "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
}
_TEENS = {
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
}
_TENS = {
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
_ZERO = {"ноль", "нуль"}
NUMBER_WORDS = set(_UNITS) | set(_TEENS) | set(_TENS) | set(_HUNDREDS) | _ZERO

_TOKEN_RE = re.compile(r"\d+|[A-Za-zА-Яа-яЁё]+")
_RUN_GAP_RE = re.compile(r"^[\s\-–—()]*$")


def words_to_digits(words: list[str]) -> str:
    """Цифры из диктовки: «сорок пять ноль восемь» -> «4508». Группы по разрядам, как их диктуют."""
    out: list[str] = []
    cur = 0
    used_h = used_t = used_u = False

    def flush() -> None:
        nonlocal cur, used_h, used_t, used_u
        if used_h or used_t or used_u:
            out.append(str(cur))
        cur, used_h, used_t, used_u = 0, False, False, False

    for w in words:
        w = w.lower()
        if w in _ZERO:
            flush()
            out.append("0")
        elif w in _HUNDREDS:
            if used_h or used_t or used_u:
                flush()
            cur += _HUNDREDS[w]
            used_h = True
        elif w in _TEENS:
            if used_t or used_u:
                flush()
            cur += _TEENS[w]
            used_t = used_u = True
        elif w in _TENS:
            if used_t or used_u:
                flush()
            cur += _TENS[w]
            used_t = True
        elif w in _UNITS:
            if used_u:
                flush()
            cur += _UNITS[w]
            used_u = True
    flush()
    return "".join(out)


@dataclass
class NumRun:
    start: int
    end: int
    digits: str


def find_number_runs(text: str) -> list[NumRun]:
    """Подряд идущие числа (цифрами и/или словами), разделённые пробелами/дефисами/скобками."""
    toks = [(m.start(), m.end(), m.group()) for m in _TOKEN_RE.finditer(text)]
    runs: list[NumRun] = []
    i = 0
    while i < len(toks):
        s, e, t = toks[i]
        if not (t.isdigit() or t.lower() in NUMBER_WORDS):
            i += 1
            continue
        j = i
        while j + 1 < len(toks):
            ns, ne, nt = toks[j + 1]
            if not (nt.isdigit() or nt.lower() in NUMBER_WORDS):
                break
            if not _RUN_GAP_RE.match(text[toks[j][1]:ns]):
                break
            j += 1
        group = toks[i:j + 1]
        digits, pending = "", []
        for _, _, tk in group:
            if tk.isdigit():
                digits += words_to_digits(pending) + tk
                pending = []
            else:
                pending.append(tk)
        digits += words_to_digits(pending)
        start, end = group[0][0], group[-1][1]
        # «+7», «плюс 7»: захватываем приставку, она нужна для границ цензуры
        if start > 0 and text[start - 1] == "+":
            start -= 1
        else:
            m = re.search(r"плюс\s+$", text[max(0, start - 8):start], re.IGNORECASE)
            if m:
                start -= len(m.group())
        runs.append(NumRun(start, end, digits))
        i = j + 1
    return runs


# ---------- контрольные суммы ----------

def inn_checksum_ok(d: str) -> bool:
    def chk(digits: str, weights: list[int]) -> int:
        return sum(int(a) * w for a, w in zip(digits, weights)) % 11 % 10

    if len(d) == 10:
        return chk(d, [2, 4, 10, 3, 5, 9, 4, 6, 8]) == int(d[9])
    if len(d) == 12:
        return chk(d, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == int(d[10]) and chk(
            d, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        ) == int(d[11])
    return False


def snils_checksum_ok(d: str) -> bool:
    if len(d) != 11:
        return False
    s = sum(int(d[i]) * (9 - i) for i in range(9))
    if s > 101:
        s %= 101
    c = 0 if s in (100, 101) else s
    return c == int(d[9:])


# ---------- классификация числовых последовательностей ----------

_KW = {
    "passport": re.compile(r"паспорт|серия|серии"),
    "inn": re.compile(r"\bинн\b|налогов"),
    "snils": re.compile(r"снилс|страхов\w*\s+свидетельств"),
    "phone": re.compile(r"телефон|звон|контакт|мобильн|связи|ватсап|вацап|whatsapp|плюс|\bномер"),
}


def _nearest_kw(ctx: str) -> str | None:
    best, best_pos = None, -1
    for typ, rx in _KW.items():
        for m in rx.finditer(ctx):
            if m.start() >= best_pos:
                best, best_pos = typ, m.start()
    return best


def classify_digits(digits: str, ctx_before: str, raw: str) -> str | None:
    """Тип по числу цифр, ближайшему ключевому слову и контрольным суммам. None — не наш тип."""
    n = len(digits)
    ctx = ctx_before.lower()[-50:]
    kw = _nearest_kw(ctx)
    plus = raw.lstrip().startswith(("+", "плюс", "Плюс"))
    if n == 11 and kw != "phone" and kw != "passport" and (kw == "snils" or snils_checksum_ok(digits) and re.search(r"\d{3}[- ]\d{3}[- ]\d{3}[ -]?\d{2}", raw)):
        return "snils"
    if n in (10, 12) and kw == "inn":
        return "inn"
    if n in (10, 12) and kw not in ("passport", "phone", "snils") and inn_checksum_ok(digits) and not re.search(r"\s", raw):
        return "inn"
    if kw == "passport" and n in (4, 6, 10):
        return "passport"
    if n == 10 and re.fullmatch(r"\d{2}\s?\d{2}\s?\d{6}", raw.strip()):
        return "passport"
    if n == 11 and digits[0] in "78" and (kw == "phone" or plus or "(" in raw or kw is None):
        return "phone"
    if n == 10 and digits[0] == "9" and (kw == "phone" or plus):
        return "phone"
    return None


def detect_numeric(text: str) -> list[Span]:
    runs = find_number_runs(text)
    out: list[Span] = []
    for idx, r in enumerate(runs):
        typ = classify_digits(r.digits, text[max(0, r.start - 60):r.start], text[r.start:r.end])
        if not typ:
            continue
        end = r.end
        # серия (4 цифры) и номер (6 цифр) паспорта диктуют раздельно: «серия … номер …»
        if typ == "passport" and len(r.digits) == 4 and idx + 1 < len(runs):
            nxt = runs[idx + 1]
            gap = text[r.end:nxt.start]
            if len(nxt.digits) == 6 and len(gap) <= 25 and not re.search(r"[.!?]", gap):
                end = nxt.end
        out.append(Span(r.start, end, typ))
    return out


# ---------- e-mail ----------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_SPOKEN_EMAIL_RE = re.compile(
    r"(?<![\w])[A-Za-z0-9_\-]+(?:\s+(?:точка|дефис|тире|подчеркивание|подчёркивание)\s+[A-Za-z0-9_\-]+)*"
    r"\s+(?:собака|собачка|эт|at)\s+"
    r"[A-Za-z0-9\-]+(?:\s+точка\s+[A-Za-z0-9\-]+)+",
    re.IGNORECASE,
)


def detect_email(text: str) -> list[Span]:
    out = [Span(m.start(), m.end(), "email") for m in _EMAIL_RE.finditer(text)]
    out += [Span(m.start(), m.end(), "email") for m in _SPOKEN_EMAIL_RE.finditer(text)]
    return out


# ---------- адреса ----------

_STREET_KW = (
    r"улиц\w*|ул\.?|проспект\w*|пр-?т\.?|переул\w+|пер\.|бульвар\w*|б-р|шоссе|набережн\w+|наб\.|"
    r"площад\w+|пл\.|проезд\w*|тупик\w*|аллея|аллеи|микрорайон\w*|мкр\.?"
)
_HOUSE_KW = r"дом|д\.|корпус|корп\.|к\.|квартира|кв\.|офис|оф\.|строение|стр\.|подъезд|этаж"
_STREET_ATOM_RE = re.compile(
    rf"(?:\b[А-Яа-яЁё\-]+(?:ий|ый|ой|ая|ое|ская|ский|ная|ной)\s+)?(?:\b(?:{_STREET_KW}))(?:\s+(?!\d)[А-Яа-яЁё][\wё\-]*)?",
    re.IGNORECASE,
)
_HOUSE_ATOM_RE = re.compile(rf"\b(?:{_HOUSE_KW})\s*\d+[А-Яа-яA-Za-z]?(?:/\d+)?", re.IGNORECASE)
_BARE_NUM_RE = re.compile(r"\d+[А-Яа-яA-Za-z]?(?:/\d+)?")
_GAP_OK_RE = re.compile(
    rf"^(?:[\s,.;–\-]|{_BARE_NUM_RE.pattern}|г\.|город|{_HOUSE_KW})*$", re.IGNORECASE
)
_HAS_KW_RE = re.compile(rf"\b(?:{_STREET_KW}|{_HOUSE_KW})", re.IGNORECASE)
_MIN_ADDR_KW = re.compile(rf"\b(?:{_STREET_KW}|{_HOUSE_KW})", re.IGNORECASE)


def build_addresses(text: str, atoms: list[tuple[int, int]]) -> list[Span]:
    """Склеивает адресные атомы (локации от нейросетей + ключевые слова улица/дом/кв.) в адреса.

    Отдельный город/район без улицы или номера дома адресом не считается.
    """
    all_atoms: list[tuple[int, int]] = list(atoms)
    for rx in (_STREET_ATOM_RE, _HOUSE_ATOM_RE):
        all_atoms += [(m.start(), m.end()) for m in rx.finditer(text)]
    all_atoms.sort()
    groups: list[list[int]] = []
    for s, e in all_atoms:
        if groups and s <= groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], e)
            continue
        if groups and s - groups[-1][1] <= 20 and _GAP_OK_RE.match(text[groups[-1][1]:s]):
            groups[-1][1] = e
            continue
        groups.append([s, e])
    out: list[Span] = []
    for s, e in groups:
        chunk = text[s:e]
        if _MIN_ADDR_KW.search(chunk):
            out.append(Span(s, e, "address"))
    return out


# ---------- слияние ----------

def merge_spans(spans: list[Span]) -> list[Span]:
    """Пересекающиеся спаны объединяются; тип берётся по приоритету."""
    spans = sorted(spans, key=lambda x: (x.start, -x.end))
    out: list[Span] = []
    for sp in spans:
        if out and sp.start < out[-1].end:
            last = out[-1]
            if TYPE_PRIORITY.get(sp.type, 99) < TYPE_PRIORITY.get(last.type, 99):
                last.type = sp.type
            last.end = max(last.end, sp.end)
        else:
            out.append(Span(sp.start, sp.end, sp.type))
    return out
