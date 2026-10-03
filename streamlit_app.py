"""Free-tier UI (Streamlit Community Cloud): Handoff Queue + Conversation Detail. Calls the agent in-process."""
import json, pathlib, sys
import streamlit as st
sys.path.insert(0, str(pathlib.Path(__file__).parent / "backend"))
from app.agent import run_conversation

st.set_page_config(page_title="Sunrise Clinic Agent", layout="wide")
ROOT = pathlib.Path(__file__).parent


@st.cache_data
def load_runs():
    runs = []
    for p in sorted((ROOT / "conversations").glob("*.json")):
        s = json.load(open(p, encoding="utf-8"))
        r = run_conversation(s["id"], s["today"], s["turns"])
        # determinism: 3 runs, compare fingerprint
        fp = {(x["terminal_state"], x["escalation_reason"]) for x in
              (run_conversation(s["id"], s["today"], s["turns"]) for _ in range(3))}
        runs.append({"script": s, "result": r, "stable": len(fp) == 1})
    return runs


runs = load_runs()
if "resolved" not in st.session_state: st.session_state.resolved = set()
page = st.sidebar.radio("Sunrise Clinic", ["Handoff Queue", "Conversation Detail"])

if page == "Handoff Queue":
    esc = [r for r in runs if r["result"]["terminal_state"] == "escalated"]
    open_ = [r for r in esc if r["script"]["id"] not in st.session_state.resolved]
    done = [r for r in runs if r["result"]["terminal_state"] in ("booked", "rescheduled", "cancelled")]
    urgent = [r for r in open_ if r["result"]["escalation_reason"] == "clinical_urgent"]
    st.title("Handoff Queue"); st.caption("Sunrise Clinic, Dehradun — conversations the agent escalated")
    c = st.columns(4)
    c[0].metric("Conversations", len(runs)); c[1].metric("Completed by agent", len(done), f"{100*len(done)//len(runs)}%")
    c[2].metric("Escalated", len(esc), f"{len(open_)} still open"); c[3].metric("Urgent", len(urgent), "clinical, unresolved")
    st.subheader("Open handoffs")
    for r in open_:
        a, b, d, e = st.columns([1, 3, 2, 1])
        a.code(r["script"]["id"]); b.write("“" + r["script"]["turns"][-1] + "”")
        d.write(f"**{r['result']['escalation_reason']}**")
        if e.button("Resolve", key=r["script"]["id"]):
            st.session_state.resolved.add(r["script"]["id"]); st.rerun()
else:
    ids = [r["script"]["id"] for r in runs]
    pick = st.selectbox("Conversation", ids)
    r = next(x for x in runs if x["script"]["id"] == pick)
    res = r["result"]
    st.title(f"Conversation {pick}"); st.caption(r["script"]["description"])
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Transcript and tool calls")
        for t in r["script"]["turns"]: st.info(f"**CALLER** {t}")
        for c in res["tool_calls"]:
            st.code(f"{c['name']}({json.dumps(c['arguments'], ensure_ascii=False)})\n→ {json.dumps(c.get('result'), ensure_ascii=False)[:300]}", language="text")
        st.success(f"**AGENT** {res['reply']}")
    with right:
        st.subheader("Outcome")
        st.json({k: res[k] for k in ("terminal_state", "escalation_reason", "patient_id", "appointment_id")} |
                {"tool_calls": len(res["tool_calls"]), "turns": res["metrics"]["turns"], "tokens": res["metrics"]["tokens"]})
        st.write("Determinism: same terminal state across 3 runs —", "**STABLE**" if r["stable"] else "**UNSTABLE**")
