# Clinic Front Desk Agent — backbone

Deterministic rule-based agent (no LLM, no API key) over six tools. Model used: none (tokens = 0).

## Run
```bash
pip install -r requirements.txt
# API
cd backend && uvicorn app.main:app --port 8000
# check against the examples (new terminal, from repo root)
python3 runner.py --url http://localhost:8000/agent/run --repeat 3
# tests
cd backend && python3 -m pytest -q
# UI (also the free-deploy target: Streamlit Community Cloud, main file = streamlit_app.py)
streamlit run streamlit_app.py
```
## Layout
- `backend/app/tools.py` six tools, no LLM, lock-protected booking, specific `ToolError` codes
- `backend/app/nlu.py` Hindi/English dates, clock times, day-parts (relative to `today`)
- `backend/app/agent.py` safety gates -> slot filling -> identity/authorisation -> tool calls
- `backend/app/main.py` `POST /agent/run` (schema.md contract)
- `streamlit_app.py` Handoff Queue + Conversation Detail screens
- `adversarial/` your 8 cases go here (see chat)
