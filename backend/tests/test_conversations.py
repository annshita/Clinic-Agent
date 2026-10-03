import json, pathlib, sys
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.agent import run_conversation
from app.tools import Clinic, ToolError

ROOT = pathlib.Path(__file__).resolve().parents[2]
FILES = sorted(list((ROOT / "conversations").glob("*.json")) + list((ROOT / "adversarial").glob("*.json")))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_conversation(path):
    s = json.load(open(path, encoding="utf-8")); e = s["expected"]
    r = run_conversation(s["id"], s["today"], s["turns"])
    names = {c["name"] for c in r["tool_calls"]}
    assert r["terminal_state"] == e["terminal_state"], r["reply"]
    assert r["escalation_reason"] == e["escalation_reason"]
    assert set(e["must_call"]) <= names and not set(e["must_not_call"]) & names
    for _ in range(2):  # determinism
        again = run_conversation(s["id"], s["today"], s["turns"])
        assert (again["terminal_state"], again["escalation_reason"], {c["name"] for c in again["tool_calls"]}) == \
               (r["terminal_state"], r["escalation_reason"], names)


def test_double_booking_rejected():
    c = Clinic("2026-10-01")
    c.book_appointment("pt_0014", "dr_rao", "2026-10-03", "10:00")
    with pytest.raises(ToolError) as ei:
        c.book_appointment("pt_0013", "dr_rao", "2026-10-03", "10:00")
    assert ei.value.code == "slot_unavailable"


def test_malformed_args_are_actionable():
    c = Clinic("2026-10-01")
    with pytest.raises(ToolError) as ei: c.search_slots("dr_rao", "3rd Oct")
    assert ei.value.code == "invalid_date"
    with pytest.raises(ToolError) as ei: c.escalate_to_human("because")
    assert ei.value.code == "invalid_reason"


def test_guardian_enforced_in_tool_layer():
    c = Clinic("2026-10-01")
    with pytest.raises(ToolError) as ei: c.cancel_appointment("ap_0003", caller_id="pt_0020")
    assert ei.value.code == "not_authorised"
