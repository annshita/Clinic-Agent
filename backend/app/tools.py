"""Tool layer: ground truth. Never calls an LLM. All state in memory, reset per run."""
import json, re, threading, pathlib
from datetime import date, datetime
from difflib import SequenceMatcher

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "clinic.json"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
REASONS = {"clinical_urgent", "medical_advice", "not_authorised", "ambiguous_patient", "out_of_scope"}


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _mins(t): h, m = t.split(":"); return int(h) * 60 + int(m)
def _hhmm(m): return f"{m // 60:02d}:{m % 60:02d}"
def _tok(s): return re.findall(r"[a-z]+", str(s).lower())


class Clinic:
    def __init__(self, today, path=DATA):
        d = json.load(open(path, encoding="utf-8"))
        self.info, self.holidays = d["clinic"], set(d["holidays"])
        self.doctors = {x["id"]: x for x in d["doctors"]}
        self.patients = {x["id"]: x for x in d["patients"]}
        self.appts = d["appointments"]
        self.today = date.fromisoformat(today)
        self.lock = threading.RLock()
        self.handoffs = []

    def _date(self, s):
        try:
            return datetime.strptime(str(s), "%Y-%m-%d").date()
        except ValueError:
            raise ToolError("invalid_date", f"date must be YYYY-MM-DD, got {s!r}")

    def _time(self, s):
        if not re.fullmatch(r"\d{2}:\d{2}", str(s)):
            raise ToolError("invalid_time", f"start must be HH:MM (24h), got {s!r}")
        return _mins(s)

    def _doctor(self, did):
        if did not in self.doctors:
            raise ToolError("unknown_doctor", f"doctor_id {did!r} not found; valid: {sorted(self.doctors)}")
        return self.doctors[did]

    def _auth(self, caller_id, patient_id):
        caller = caller_id or patient_id
        if caller not in self.patients:
            raise ToolError("unknown_patient", f"caller_id {caller!r} not found")
        if caller != patient_id and patient_id not in self.patients[caller]["guardian_of"]:
            raise ToolError("not_authorised", f"{caller} is not the patient or a listed guardian of {patient_id}")

    def search_slots(self, doctor_id, date):
        doc, d = self._doctor(doctor_id), self._date(date)
        if d < self.today:
            raise ToolError("date_in_past", f"{date} is before today ({self.today})")
        base = {"doctor_id": doctor_id, "date": str(date), "slots": [], "closed_reason": None}
        if str(date) in self.holidays: return {**base, "closed_reason": "holiday"}
        if str(date) in doc["leave_dates"]: return {**base, "closed_reason": "doctor_on_leave"}
        wins = [w for w in doc["windows"] if w["day"] == DAYS[d.weekday()]]
        if not wins: return {**base, "closed_reason": "no_window"}
        step = self.info["slot_minutes"]
        free = set()
        for w in wins:  # overlapping windows (Rao, Mon) merge
            free |= set(range(_mins(w["start"]), _mins(w["end"]) - step + 1, step))
        taken = {_mins(a["start"]) for a in self.appts
                 if a["doctor_id"] == doctor_id and a["date"] == str(date) and a["status"] == "booked"}
        return {**base, "slots": [_hhmm(m) for m in sorted(free - taken)]}

    def book_appointment(self, patient_id, doctor_id, date, start, caller_id=None):
        with self.lock:
            if patient_id not in self.patients:
                raise ToolError("unknown_patient", f"patient_id {patient_id!r} not found")
            self._auth(caller_id, patient_id)
            if start not in self.search_slots(doctor_id, date)["slots"]:
                raise ToolError("slot_unavailable", f"{start} is not a free slot for {doctor_id} on {date}")
            end = _hhmm(self._time(start) + self.info["slot_minutes"])
            ap = {"id": f"ap_{len(self.appts) + 1:04d}", "patient_id": patient_id, "doctor_id": doctor_id,
                  "date": str(date), "start": start, "end": end, "status": "booked"}
            self.appts.append(ap)
            return ap

    def _appt(self, appointment_id):
        for a in self.appts:
            if a["id"] == appointment_id and a["status"] == "booked":
                return a
        raise ToolError("unknown_appointment", f"no booked appointment {appointment_id!r}")

    def reschedule_appointment(self, appointment_id, date, start, caller_id=None):
        with self.lock:
            a = self._appt(appointment_id)
            self._auth(caller_id, a["patient_id"])
            if (a["date"], a["start"]) == (str(date), start):
                raise ToolError("same_slot", "appointment is already at that slot")
            if start not in self.search_slots(a["doctor_id"], date)["slots"]:
                raise ToolError("slot_unavailable", f"{start} is not a free slot for {a['doctor_id']} on {date}")
            a.update(date=str(date), start=start, end=_hhmm(self._time(start) + self.info["slot_minutes"]))
            return a

    def cancel_appointment(self, appointment_id, caller_id=None):
        with self.lock:
            a = self._appt(appointment_id)
            self._auth(caller_id, a["patient_id"])
            a["status"] = "cancelled"
            return a

    def lookup_patient(self, name=None, phone=None):
        if not name and not phone:
            raise ToolError("missing_argument", "lookup_patient needs name and/or phone")
        if phone is not None:
            phone = re.sub(r"\D", "", str(phone))
            if len(phone) != 10:
                raise ToolError("invalid_phone", f"phone must be 10 digits, got {phone!r}")
        pool = [p for p in self.patients.values() if not phone or p["phone"] == phone]
        if name:
            q = _tok(name)
            exact = [p for p in pool if _tok(p["name"]) == q]
            if exact and phone:
                pool = exact
            elif exact:  # near-duplicate names stay ambiguous unless a phone settles it
                near = [p for p in pool if p not in exact and
                        SequenceMatcher(None, " ".join(q), " ".join(_tok(p["name"]))).ratio() >= 0.85]
                pool = exact + near
            else:
                pool = [p for p in pool if q and all(any(pt == t or (len(t) == 1 and pt.startswith(t))
                                                         for pt in _tok(p["name"])) for t in q)]
        out = []
        for p in pool:
            ups = [{k: a[k] for k in ("id", "doctor_id", "date", "start")} for a in self.appts
                   if a["patient_id"] == p["id"] and a["status"] == "booked" and a["date"] >= str(self.today)]
            out.append({"id": p["id"], "name": p["name"], "phone": p["phone"], "dob": p["dob"],
                        "guardian_of": p["guardian_of"], "upcoming_appointments": ups})
        return {"candidates": out}

    def escalate_to_human(self, reason, detail="", conversation_id=None):
        if reason not in REASONS:
            raise ToolError("invalid_reason", f"reason must be one of {sorted(REASONS)}, got {reason!r}")
        h = {"id": f"ho_{len(self.handoffs) + 1:04d}", "reason": reason, "detail": detail,
             "conversation_id": conversation_id, "status": "open"}
        self.handoffs.append(h)
        return h
