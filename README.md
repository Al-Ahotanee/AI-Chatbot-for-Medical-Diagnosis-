# AI-Powered Chatbot for Medical Diagnosis

**Final Year Project — Umar Sadi Dan Malam, Sokoto State University (SLU)**

A symptom-assessment chatbot that helps a visitor understand their symptoms
and urgency level before seeing a physician. The system is built around a
**dual-engine architecture** so it keeps working even when the online AI
engine is offline, rate-limited, or has used up its daily quota.

---

## How it stays reliable

1. **Case Memory (PostgreSQL / Neon)** — every diagnosis generated is
   fingerprinted from the visitor's own description and stored. If the
   same case is presented again (by anyone), the saved response is served
   instantly instead of calling the AI engine again.

2. **Online AI Engine (Google Gemini)** — the primary reasoning engine,
   used whenever it is configured, reachable, and under its daily quota.

3. **Built-in Diagnostic Engine (`engine.py`)** — a robust, rule-based
   fallback with its own symptom lexicon, red-flag emergency detection,
   and a knowledge base of ~20 common conditions. It takes over
   automatically and tells the visitor it has done so whenever the online
   engine is busy, offline, unconfigured, or has hit its daily limit.

```
visitor message
      │
      ▼
 seen this exact case before?  ──yes──▶ return saved result instantly
      │ no
      ▼
 online AI engine available & under quota? ──yes──▶ try it
      │ no / it failed
      ▼
 built-in diagnostic engine generates the assessment
      │
      ▼
 result saved to case memory for next time
```

---

## Project structure

```
app.py              Main Flask application (routes, engine orchestration)
App.py              Thin compatibility re-export of app.py (kept for any
                     existing deployment config referencing "App:app")
engine.py           Built-in rule-based diagnostic engine
db.py               PostgreSQL (Neon) case memory + usage tracking
index.html          Single-page frontend (landing page + chat console)
requirements.txt    Python dependencies
render.yaml          Render.com deployment configuration
.env.example         Template for local environment variables
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create a free Neon Postgres database
1. Go to https://neon.tech and create a free project.
2. Copy the **connection string** it gives you (it looks like
   `postgresql://user:password@ep-xxxx.neon.tech/dbname`).
3. Paste it into your `.env` file as `DATABASE_URL`.

The required tables (`diagnosis_cases`, `engine_usage_log`) are created
automatically the first time the app starts — no manual migration needed.

### 3. Configure environment variables
Copy `.env.example` to `.env` and fill in:

```
GEMINI_API_KEY=your-gemini-api-key       # optional — leave blank to always use the built-in engine
DATABASE_URL=your-neon-connection-string  # optional — leave blank to run without persistence
MAX_AI_REQUESTS_PER_DAY=50                # daily ceiling before auto-fallback kicks in
```

### 4. Run locally
```bash
python app.py
```
Visit `http://localhost:5000`.

### 5. Deploy
`render.yaml` is preconfigured for Render.com's free tier. Set
`GEMINI_API_KEY` and `DATABASE_URL` as secret environment variables in the
Render dashboard after creating the service.

---

## Important note

This system provides preliminary, educational health information only.
It is **not** a substitute for professional medical advice, diagnosis, or
treatment. Always consult a qualified physician for any health concern.
