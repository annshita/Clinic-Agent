# Clinic Front Desk Agent

A conversational front-desk agent for Sunrise Clinic, Dehradun. It books, reschedules and cancels appointments in Hindi, English and Hinglish, and escalates to a human when it should not act.

- **Live app (React):** https://clinic-agent-lilac.vercel.app/
- **API:** https://clinic-agent-yenx.onrender.com (free tier, so the first request after idle can take up to a minute)

## Run it locally

```bash
pip install -r requirements.txt && cd backend && uvicorn app.main:app --port 8000
```

Frontend, in a second terminal:

```bash
cd frontend && npm install && echo "VITE_API=http://localhost:8000" > .env && npm run dev
```

Check against the example conversations (from the repo root, with the backend running):

```bash
python3 runner.py --repeat 3
```

Tests (15 given examples, 8 adversarial cases, 3 tool-layer tests):

```bash
cd backend && python3 -m pytest -q
```

## Model used

None. The agent is deterministic and rule-based: no LLM, no API key and no randomness. I chose this on purpose because the brief scores safety and the worst of three runs. See `DECISIONS.md`.

## Structure

| Path | What it is |
|---|---|
| `backend/app/tools.py` | The six tools. They never call an LLM, and they are the ground truth. |
| `backend/app/nlu.py` | Hindi/English date, clock-time and day-part parsing. Dates resolve against `today`, never the system clock. |
| `backend/app/agent.py` | Safety checks, slot filling, patient and authorisation resolution, tool calls. |
| `backend/app/main.py` | REST API. |
| `frontend/` | React app: Handoff Queue and Conversation Detail. |
| `adversarial/` | 8 cases that break a naive agent, in the `schema.md` format. |
| `streamlit_app.py` | Alternative UI that runs the agent in-process. |
| `DECISIONS.md` | Ambiguities found, what I chose, and why. |

## How the agent decides

1. **Clinical urgency is checked first.** Chest pain, breathing trouble and similar phrases escalate as `clinical_urgent` before any booking logic runs.
2. **Medical-advice questions** escalate as `medical_advice`.
3. **Injected or bulk instructions** are ignored. If nothing legitimate remains, the result is `refused`.
4. **Slots are extracted** from all turns, with mid-sentence corrections handled.
5. **The caller is identified** with `lookup_patient`, and a guardian or other third party is checked for authorisation. Ambiguous matches escalate as `ambiguous_patient`, and unauthorised requests as `not_authorised`.
6. **One write happens at the end:** `book_appointment`, `reschedule_appointment` or `cancel_appointment`. Every fact in the reply comes from a tool result.

## API contracts

### `POST /agent/run`

Request:
```json
{ "conversation_id": "cv_0001", "today": "2026-10-01", "turns": ["...", "..."] }
```

Response:
```json
{
  "conversation_id": "cv_0001",
  "tool_calls": [{ "name": "search_slots", "arguments": {}, "result": {} }],
  "terminal_state": "booked",
  "escalation_reason": null,
  "patient_id": "pt_0013",
  "appointment_id": "ap_0026",
  "reply": "...",
  "metrics": { "turns": 3, "tokens": 0 }
}
```

`terminal_state` is one of `booked`, `rescheduled`, `cancelled`, `escalated`, `refused`, `abandoned`. `escalation_reason` is one of `clinical_urgent`, `medical_advice`, `not_authorised`, `ambiguous_patient`, `out_of_scope`, and is `null` unless the state is `escalated`.

### Endpoints used by the UI

| Method and path | Returns |
|---|---|
| `GET /stats` | Counters: total, completed, escalated, open, urgent |
| `GET /handoffs` | Open escalated conversations |
| `POST /handoffs/{id}/resolve` | Marks a handoff resolved (in memory) |
| `GET /conversations` | All seeded conversations with their results |

### Tools

`search_slots`, `book_appointment`, `reschedule_appointment`, `cancel_appointment`, `lookup_patient`, `escalate_to_human`. Bad arguments return a specific error code (for example `invalid_date` or `slot_unavailable`), not a generic 500.

## Efficiency

There are no model tokens (0 per conversation). Each conversation ran in about 1 to 3 ms locally when I ran `runner.py`. On the hosted API the response time is dominated by network latency, plus a cold start on Render's free tier after idle.

## Known limits

- It only recognises the Hindi, English and Hinglish phrases in its word lists.
- Negated or past-tense symptom mentions also escalate. This is deliberate: a missed emergency costs more than an extra handoff.
- State is in memory and resets on restart, which the brief allows.

## Author
Anshita Verma