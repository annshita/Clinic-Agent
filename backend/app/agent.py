"""Conversation layer. Deterministic: safety gates first, then slot-filling, then tool calls.
Every fact in `reply` is read from a tool result. Writes happen once, after all turns are read."""
import re
from .nlu import norm, segments, dates_in, time_in, PART_RANGE
from .tools import Clinic, ToolError, _hhmm

URGENT = re.compile(
    r"(seene|seena|chhati|chati|chest)\W+(?:\w+\W+){0,4}(dard|pain|bhaari|bhari|tight|dabav|jalan)|"
    r"(saans|sans|breath)\W+(?:\w+\W+){0,4}(phool|phul|takleef|nahi aa|nahin aa|ruk|dikkat|ukhad|tight|difficult|short)|"
    r"(shortness of breath|breathless|can'?t breathe|cannot breathe|heart attack|dil ka daura|stroke|lakwa|seizure|"
    r"mirgi|daura pad|behosh|unconscious|passed out|collapsed|faint(ed|ing)|bahut khoon|heavy bleeding|"
    r"khoon ki ulti|vomiting blood|zeher|poison|overdose|sab goliyan|suicide|jaan de|marna chah|"
    r"chehra tedha|face drooping|bol nahi pa|slurred|neela pad|emergency|ambulance)|सीने|सांस|बेहोश",
    re.I)
MEDQ = re.compile(
    r"\b(le lun|le lu|le sakta|le sakti|le skta|kha lun|kha lu|dose|dosage|kitni goli|kitni dawai|kitni baar|"
    r"kaun si dawai|konsi dawai|which medicine|should i take|can i take|is it safe|side effects?|"
    r"serious hai|serious to nahi|kya hua hai mujhe|kya bimari|diagnos\w*)\b")
OOS = re.compile(r"\b(report|bill|refund|insurance|certificate|prescription|refill|lab result|test result|invoice|home visit)\b")
INJ = re.compile(r"ignore (your|all|previous|the)|administrator|admin mode|system prompt|internal test|"
                 r"sabhi appointments?|every appointment|all appointments|override|jailbreak|developer mode")
CANCEL = re.compile(r"\bcancel|\braddh?\b|\bhata\b|mat rakhiye")
RESCH = re.compile(r"reschedule|badal|\bshift\b|\bmove\b|postpone|prepone|\bchange\b|\buse\b.*(karwa|kar\b|kijiye|karna)")
BOOK = re.compile(r"appointment|milna|dikhana|dikhwana|\bbook\b|aa sakta|aa sakti|consult|\bslot\b|\bmil sakta")
DOCS = [("dr_rao", re.compile(r"\brao\b|anjali|general physician")), ("dr_sethi", re.compile(r"sethi|vikram|paediatric|pediatric"))]
POSTP = {"ka", "ki", "ke", "ko"}
CHILD = re.compile(r"\b(bete|beta|beti|bacche|bachche|bachcha|baccha|son|daughter|child|kid)\b")
NONGUARD = re.compile(r"padosi|neighbou?r|dost|friend|colleague")
MAIN = re.compile(r"\b(main|mai|mera naam|my name is|i am|this is)\b")


class Rec:
    def __init__(self, clinic, cid):
        self.c, self.cid, self.calls = clinic, cid, []

    def call(self, tool, **kw):
        entry = {"name": tool, "arguments": kw}
        self.calls.append(entry)
        try:
            res = getattr(self.c, tool)(**kw)
        except ToolError as e:
            res = {"error": e.code, "message": e.message}
        except Exception as e:  # never crash the request
            res = {"error": "internal", "message": str(e)}
        entry["result"] = res
        return res


def _runs(text, vocab):
    toks = [(m.group(), m.start(), m.end()) for m in re.finditer(r"[a-z]+", text)]
    runs, cur = [], []
    for i, (w, s, e) in enumerate(toks):
        if w in vocab and (not cur or re.fullmatch(r"[\s.]*", text[cur[-1][2]:s])):
            cur.append((w, s, e))
        else:
            if cur: runs.append(cur)
            cur = [(w, s, e)] if w in vocab else []
    if cur: runs.append(cur)
    out = []
    for r in runs:
        if not any(len(w) > 2 for w, _, _ in r): continue
        after = [m.group() for m in re.finditer(r"[a-z]+", text[r[-1][2]:])][:3]
        after = [w for w in after if w != "ji"]
        out.append({"name": " ".join(w for w, _, _ in r), "next": after[0] if after else "", "start": r[0][1]})
    return out


def run_conversation(cid, today, turns):
    clinic = Clinic(today)
    rec = Rec(clinic, cid)
    turns = [str(t) for t in (turns or []) if isinstance(t, str)]
    texts = [norm(t) for t in turns]
    n = len(turns)

    def out(state, reply, reason=None, pid=None, aid=None):
        return {"conversation_id": cid, "tool_calls": rec.calls, "terminal_state": state,
                "escalation_reason": reason if state == "escalated" else None,
                "patient_id": pid, "appointment_id": aid, "reply": reply, "metrics": {"turns": n, "tokens": 0}}

    def escalate(reason, detail, reply):
        rec.call("escalate_to_human", reason=reason, detail=detail[:300], conversation_id=cid)
        return out("escalated", reply, reason)

    # 1. HARD RULE: clinical urgency stops everything, before any other work.
    for i, t in enumerate(texts):
        if URGENT.search(t):
            return escalate("clinical_urgent", f"caller said: {turns[i]}",
                            "Aapki baat sunkar lagta hai turant doctor ki zaroorat hai. Main abhi clinic staff se connect "
                            "kar rahi hoon. Agar dard ya saans ki takleef badh rahi hai to turant 112 par call karein "
                            "ya nazdeeki emergency mein jaayein.")
    # 2. Clinical judgement requested.
    for i, t in enumerate(texts):
        if MEDQ.search(t):
            return escalate("medical_advice", f"caller said: {turns[i]}",
                            "Dawai ya ilaaj ke baare mein main salaah nahi de sakti. Main aapko clinic ke staff se "
                            "jod rahi hoon, woh aapse baat karenge.")
    # 3. Prompt injection / bulk requests: ignore those turns.
    bad = [bool(INJ.search(t)) for t in texts]
    good = [t for t, b in zip(texts, bad) if not b]
    full = " . ".join(good)
    has_intent = bool(CANCEL.search(full) or RESCH.search(full) or BOOK.search(full))
    if not has_intent and any(OOS.search(t) for t in good):
        return escalate("out_of_scope", "; ".join(turns)[:300], "Yeh request front desk ke dayre se bahar hai, "
                        "main aapko staff se jod rahi hoon.")
    if not good:
        return out("refused", "Maaf kijiye, main yeh request poori nahi kar sakti. Appointment book, badalne ya cancel "
                   "karne mein madad kar sakti hoon.")

    # 4. Slot filling.
    today_d = clinic.today
    intent = "cancel" if CANCEL.search(full) else "reschedule" if RESCH.search(full) else "book" if BOOK.search(full) else None
    doctor = None
    for t in good:
        for d, rx in DOCS:
            if rx.search(t): doctor = d
    dlist, conflict, has_or, tmin, part, anyt = [], False, False, None, None, False
    for t in good:
        for seg in reversed(segments(t)):
            dl, cf, orr = dates_in(seg, today_d)
            if dl: dlist, conflict, has_or = dl, cf, orr; break
        for seg in reversed(segments(t)):
            tm, pt, an = time_in(seg)
            if tm is not None or pt or an: tmin, part, anyt = tm, pt, an; break
    if intent is None and (doctor or dlist or tmin is not None):
        intent = "book"

    # 4b. Fail fast on days with no slots at all, before asking for identity.
    if intent == "book" and doctor and dlist and not conflict:
        chk = [rec.call("search_slots", doctor_id=doctor, date=d) for d in (sorted(dlist) if has_or else dlist[-1:])]
        if all(not r.get("slots") for r in chk):
            r0 = chk[0]
            return out("abandoned", f"{r0.get('date', dlist[-1])} ko {clinic.doctors[doctor]['name']} ke paas koi slot "
                       f"nahi hai ({r0.get('closed_reason') or r0.get('message')}). Kripya doosri tareekh bataiye.")
    # 5. Identify caller and (if different) the patient.
    vocab = {w for p in clinic.patients.values() for w in re.findall(r"[a-z]+", p["name"].lower())}
    phones = re.findall(r"(?<!\d)\d{10}(?!\d)", re.sub(r"(?<=\d)[ -](?=\d)", "", full))
    phone = phones[-1] if phones else None
    self_names, subj_names = [], []
    for t in good:
        runs = _runs(t, vocab)
        has_phone = bool(re.search(r"\d{10}", re.sub(r"(?<=\d)[ -](?=\d)", "", t)))
        for k, r in enumerate(runs):
            if r["next"] in POSTP or r["next"] in {"mera", "meri", "my"}: subj_names.append(r["name"])
            elif r["next"] in {"bol", "speaking", "here"} or MAIN.search(t) or (has_phone and k == 0):
                self_names.append(r["name"])
            else: subj_names.append(r["name"])
    if intent is None and not (self_names or subj_names or phone):
        return out("abandoned", "Maaf kijiye, mujhe aapki baat samajh nahi aayi. Kripya apna naam, number aur "
                   "kis doctor ke saath appointment chahiye, bataiye.")
    if intent is None:
        return out("abandoned", "Aap kya karwana chahte hain - appointment book, badalna ya cancel?")

    caller = None
    if self_names or phone:
        kw = {k: v for k, v in (("name", self_names[-1] if self_names else None), ("phone", phone)) if v}
        c = rec.call("lookup_patient", **kw).get("candidates", [])
        if len(c) > 1:
            return escalate("ambiguous_patient", f"{len(c)} matches: {[x['id'] for x in c]}",
                            "Aapke record mein ek se zyada match mil rahe hain, staff aapse confirm karke madad karenge.")
        caller = c[0] if c else None
        if not caller:
            return out("abandoned", "Is naam aur number se koi record nahi mila. Kripya sahi naam aur number bataiye.")
    patient = caller
    subj = sorted(set(subj_names))
    if caller is None:
        if NONGUARD.search(full):
            return escalate("not_authorised", "caller not identified and acting for a third party",
                            "Doosre mareez ke record par main badlav nahi kar sakti, staff aapse baat karenge.")
        if subj:
            c = rec.call("lookup_patient", name=subj[0]).get("candidates", [])
            if len(c) > 1:
                return escalate("ambiguous_patient", f"{len(c)} matches: {[x['id'] for x in c]}",
                                "Is naam ke kai mareez hain, staff aapse confirm karke madad karenge.")
        return out("abandoned", "Kripya apna poora naam aur registered phone number bataiye.")
    if subj or (CHILD.search(full) or NONGUARD.search(full)):
        cands = []
        for s in subj:
            cands += rec.call("lookup_patient", name=s).get("candidates", [])
        ids = {c["id"] for c in cands}
        if caller["id"] in ids:
            pass
        elif subj:
            deps = [c for c in cands if c["id"] in caller["guardian_of"]]
            if len(deps) == 1: patient = deps[0]
            elif len(deps) > 1:
                return escalate("ambiguous_patient", f"dependents {[d['id'] for d in deps]}", "Kaun sa mareez? Staff confirm karenge.")
            elif cands:
                return escalate("not_authorised", f"{caller['id']} is not patient/guardian of {sorted(ids)}",
                                "Kisi aur ke record par badlav ke liye main authorised nahi hoon. Staff aapse baat karenge.")
            else:
                return out("abandoned", "Is naam ka koi mareez nahi mila. Kripya naam dobara bataiye.")
        else:  # only "mere bete ke liye", no name
            deps = caller["guardian_of"]
            if len(deps) > 1:
                return escalate("ambiguous_patient", f"{len(deps)} dependents, none named", "Kaun sa bachcha? Staff confirm karenge.")
            if not deps:
                return escalate("not_authorised", "no listed dependents", "Aap is record ke guardian nahi hain. Staff aapse baat karenge.")
            patient = rec.call("lookup_patient", name=clinic.patients[deps[0]]["name"], phone=clinic.patients[deps[0]]["phone"])["candidates"][0]
    pid = patient["id"]

    # 6. Act.
    if conflict:
        return out("abandoned", "Tareekh aur din mel nahi kha rahe. Kripya sahi tareekh bataiye.", pid=pid)
    if intent in ("cancel", "reschedule"):
        ups = [a for a in patient["upcoming_appointments"] if not doctor or a["doctor_id"] == doctor]
        exist = dlist[0] if dlist and (intent == "cancel" or len(dlist) > 1) else None
        if exist: ups = [a for a in ups if a["date"] == exist]
        if len(ups) != 1:
            return out("abandoned", "Mujhe aapka ek appointment nahi mil paya ya kai mile. Kripya tareekh aur doctor bataiye."
                       if ups else "Aapka koi upcoming appointment nahi mila.", pid=pid)
        ap = ups[0]
        if intent == "cancel":
            r = rec.call("cancel_appointment", appointment_id=ap["id"], caller_id=caller["id"])
            if "error" in r: return out("abandoned", f"Cancel nahi ho paya: {r['message']}", pid=pid)
            return out("cancelled", f"Ji, {r['date']} {r['start']} ka appointment cancel ho gaya hai.", pid=pid, aid=r["id"])
        doctor, dlist = ap["doctor_id"], dlist[-1:]
    if not doctor:
        return out("abandoned", "Kis doctor ke saath appointment chahiye? Dr. Rao ya Dr. Sethi?", pid=pid)
    if not dlist:
        return out("abandoned", "Kis tareekh ko aana chahenge?", pid=pid)
    if tmin is None and not part and not anyt:
        return out("abandoned", "Kaunsa time theek rahega - subah, dopahar ya shaam?", pid=pid)
    if has_or and intent == "book": dlist = sorted(dlist)
    else: dlist = dlist[-1:]
    shown = None
    for d in dlist:
        res = rec.call("search_slots", doctor_id=doctor, date=d)
        slots = res.get("slots", [])
        if not slots:
            shown = shown or (res.get("closed_reason") or res.get("message"), d, []); continue
        if tmin is not None: pick = _hhmm(tmin) if _hhmm(tmin) in slots else None
        elif part:
            lo, hi = PART_RANGE[part]
            pick = next((s for s in slots if lo <= int(s[:2]) * 60 + int(s[3:]) < hi), None)
        else: pick = slots[0]
        if pick:
            fn = "book_appointment" if intent == "book" else "reschedule_appointment"
            kw = dict(patient_id=pid, doctor_id=doctor, date=d, start=pick, caller_id=caller["id"]) if intent == "book" \
                else dict(appointment_id=ap["id"], date=d, start=pick, caller_id=caller["id"])
            r = rec.call(fn, **kw)
            if "error" in r: return out("abandoned", f"Slot book nahi ho paya: {r['message']}", pid=pid)
            who = clinic.doctors[r["doctor_id"]]["name"]
            verb = "book" if intent == "book" else "reschedule"
            return out("booked" if intent == "book" else "rescheduled",
                       f"Ji, {r['date']} ko {r['start']} baje {who} ke saath appointment {verb} ho gaya hai.",
                       pid=pid, aid=r["id"])
        shown = shown or ("requested time unavailable", d, slots)
    why, d, slots = shown if shown else ("unavailable", dlist[0], [])
    if slots:
        return out("abandoned", f"{d} ko woh time available nahi hai. Available slots: {', '.join(slots[:6])}.", pid=pid)
    return out("abandoned", f"{d} ko {clinic.doctors[doctor]['name']} ke paas koi slot nahi hai ({why}).", pid=pid)
