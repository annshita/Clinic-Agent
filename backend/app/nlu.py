"""Deterministic Hindi/English/Hinglish extraction. Dates resolve against `today`, never the clock."""
import re, unicodedata
from datetime import date, timedelta

WD = {"monday": 0, "mon": 0, "somwar": 0, "somvar": 0, "tuesday": 1, "tue": 1, "mangalwar": 1, "mangalvar": 1,
      "wednesday": 2, "wed": 2, "budhwar": 2, "budhvar": 2, "thursday": 3, "thu": 3, "guruwar": 3, "guruvar": 3,
      "brihaspatiwar": 3, "veerwar": 3, "friday": 4, "fri": 4, "shukrawar": 4, "shukravar": 4,
      "saturday": 5, "sat": 5, "shanivaar": 5, "shaniwar": 5, "shanivar": 5,
      "sunday": 6, "sun": 6, "ravivaar": 6, "raviwar": 6, "ravivar": 6, "itwaar": 6}
REL = {"aaj": 0, "today": 0, "kal": 1, "tomorrow": 1, "parso": 2, "parson": 2, "narso": 3}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
HI = {"ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6, "cheh": 6,
      "saat": 7, "aath": 8, "nau": 9, "das": 10, "gyarah": 11, "barah": 12, "baarah": 12}
BREAK = re.compile(r"nahi nahi|nahin nahin|no no|i mean|actually|matlab|sorry|\bnahi\b,|\bnahin\b,|\brather\b")
ANY = re.compile(r"koi bhi|kabhi bhi|jab bhi|any ?time|jo mil jaye|jo bhi|whenever|earliest|sabse pehle")
PARTS = [("morning", re.compile(r"subah|morning|savere")), ("afternoon", re.compile(r"dopahar|afternoon")),
         ("evening", re.compile(r"shaam|sham\b|evening|raat|night"))]
PART_RANGE = {"morning": (0, 720), "afternoon": (720, 960), "evening": (960, 1440)}


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(s)).lower()).strip()


def segments(t):
    return [s for s in BREAK.split(t) if s and s.strip()] or [t]


def _resolve(d, today):
    return today + timedelta(days=d)


def dates_in(seg, today):
    """-> (ordered ISO dates, conflict, has_or). conflict = weekday and day-number disagree."""
    found = []  # (pos, kind, date)
    t = seg.replace("day after tomorrow", "parso")
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        found.append((m.start(), "iso", date(int(m[1]), int(m[2]), int(m[3]))))
    for m in re.finditer(r"\b([a-z]+)\b", t):
        w = m[1]
        if w in REL: found.append((m.start(), "rel", _resolve(REL[w], today)))
        elif w in WD:
            delta = (WD[w] - today.weekday()) % 7 or 7
            found.append((m.start(), "wd", _resolve(delta, today)))
    nums = list(re.finditer(r"(?<![\d:.])(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:tareekh|tarikh|tarik|date)\b", t)) + \
        list(re.finditer(r"(?<![\d:.])(\d{1,2})(?:st|nd|rd|th)\b", t))
    for m in nums:
        d = int(m[1]); mo, yr = today.month, today.year
        mm = re.match(r"\s*(?:of\s+)?([a-z]{3})", t[m.end():])
        if mm and mm[1] in MONTHS: mo = MONTHS[mm[1]]
        try:
            c = date(yr, mo, d)
            if c < today: c = date(yr + (mo == 12), mo % 12 + 1, d) if not (mm and mm[1] in MONTHS) else date(yr + 1, mo, d)
            found.append((m.start(), "num", c))
        except ValueError:
            pass
    found.sort(key=lambda x: x[0])
    wds = {d for _, k, d in found if k == "wd"}; ns = {d for _, k, d in found if k == "num"}
    conflict = bool(wds and ns and not (wds & ns) and len(wds) == 1 and len(ns) == 1)
    ordered = []
    for _, _, d in found:
        if not ordered or ordered[-1] != d: ordered.append(d)
    return [d.isoformat() for d in ordered], conflict, bool(re.search(r"\b(ya|or)\b", t))


def _hour(h, ampm, part):
    if ampm: return h % 12 + (12 if ampm == "pm" else 0)
    if part in ("afternoon", "evening"): return h + 12 if h < 12 else h
    if part == "morning": return h
    return h + 12 if 1 <= h <= 7 else h


def time_in(seg):
    """-> (minutes or None, part_of_day or None, any_time)"""
    part = next((p for p, rx in PARTS if rx.search(seg)), None)
    hits = []
    for m in re.finditer(r"(?<![\d-])(\d{1,2})[:.](\d{2})\s*(am|pm)?", seg):
        hits.append((m.start(), _hour(int(m[1]), m[3], part) * 60 + int(m[2])))
    for m in re.finditer(r"(?<![\d:.])(\d{1,2})\s*(baje|am\b|pm\b|o'?clock)", seg):
        ap = m[2] if m[2] in ("am", "pm") else None
        hits.append((m.start(), _hour(int(m[1]), ap, part) * 60))
    for m in re.finditer(r"\b(saade|sade|sava|paune|dedh|dhai)?\s*(" + "|".join(HI) + r")?\s*baje", seg):
        pre, w = m[1], m[2]
        if pre == "dedh": mins = 13 * 60 + 30
        elif pre == "dhai": mins = 14 * 60 + 30
        elif w:
            h = HI[w]; base = _hour(h, None, part)
            mins = {"saade": base * 60 + 30, "sade": base * 60 + 30, "sava": base * 60 + 15,
                    "paune": (base - 1) * 60 + 45}.get(pre, base * 60)
        else: continue
        hits.append((m.start(), mins))
    hits.sort()
    return (hits[-1][1] if hits else None), part, bool(ANY.search(seg))
