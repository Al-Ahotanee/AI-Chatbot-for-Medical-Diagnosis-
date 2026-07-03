"""
MediBot — Flask backend with Dual Engine (Rule-Based + Gemini AI)
"""
import os
import re
import json
import uuid
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime
from flask import Flask, request, jsonify, send_file, g

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost:5432/medibot")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") # Set this in Render env vars
APP_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Medical Knowledge Base (Same as before)
# ---------------------------------------------------------------------------
SYMPTOMS = {
    "fever": ["fever", "feverish", "high temperature", "running a temperature", "temperature"],
    "cough": ["cough", "coughing"],
    "sore_throat": ["sore throat", "throat pain", "throat hurts", "scratchy throat", "painful swallowing"],
    "runny_nose": ["runny nose", "nasal discharge", "stuffy nose", "blocked nose", "congestion", "congested"],
    "sneezing": ["sneeze", "sneezing"],
    "headache": ["headache", "head ache", "head hurts", "head pain", "headaches"],
    "fatigue": ["fatigue", "tired", "exhausted", "weak", "no energy", "lethargic", "drained"],
    "body_ache": ["body ache", "muscle pain", "muscle ache", "body aches", "sore muscles", "aches"],
    "shortness_breath": ["shortness of breath", "breathless", "difficulty breathing", "can't breathe", "cannot breathe", "trouble breathing", "dyspnea", "hard to breathe"],
    "chest_pain": ["chest pain", "chest pressure", "chest tightness", "pain in chest", "chest discomfort"],
    "nausea": ["nausea", "nauseous", "queasy", "sick to stomach", "feeling sick"],
    "vomiting": ["vomiting", "throw up", "throwing up", "puke", "puking", "emesis", "barf"],
    "diarrhea": ["diarrhea", "diarrhoea", "loose stool", "loose motion", "watery stool", "loose motions"],
    "abdominal_pain": ["abdominal pain", "stomach pain", "belly pain", "stomach ache", "tummy ache", "cramps", "stomach cramps", "belly ache"],
    "dizziness": ["dizzy", "dizziness", "lightheaded", "light-headed", "vertigo"],
    "loss_smell": ["loss of smell", "can't smell", "no smell", "loss of taste", "can't taste"],
    "rash": ["rash", "skin rash", "hives", "skin breakout", "skin bumps"],
    "joint_pain": ["joint pain", "aching joints", "swollen joints", "joints hurt"],
    "frequent_urination": ["frequent urination", "peeing a lot", "urinate often", "urinating often", "peeing often"],
    "excessive_thirst": ["excessive thirst", "very thirsty", "always thirsty", "extreme thirst"],
    "weight_loss": ["weight loss", "losing weight", "unexplained weight loss"],
    "blurred_vision": ["blurred vision", "blurry vision", "can't see clearly", "fuzzy vision"],
    "burning_urination": ["burning urination", "painful urination", "burning when peeing", "burns when i pee"],
    "chills": ["chills", "shivering", "shaking with cold", "shivers"],
    "wheezing": ["wheezing", "wheeze", "whistling breath"],
    "sensitivity_light": ["sensitivity to light", "light bothers", "bright light hurts", "light sensitive"],
    "stiff_neck": ["stiff neck", "neck stiffness", "can't move neck"],
    "confusion": ["confusion", "confused", "disoriented", "can't think straight"],
    "anxiety": ["anxiety", "anxious", "panic", "nervous", "worried", "restless"],
    "insomnia": ["insomnia", "can't sleep", "trouble sleeping", "sleepless", "unable to sleep"],
    "back_pain": ["back pain", "lower back pain", "upper back pain", "backache"],
    "loss_appetite": ["loss of appetite", "no appetite", "not hungry", "don't want to eat"],
}

CONDITIONS = {
    "common_cold": {"name": "Common Cold", "cardinal": ["runny_nose", "sneezing", "sore_throat"], "common": ["cough", "fatigue", "headache", "body_ache"], "advice": "Rest, stay hydrated, and use over-the-counter remedies."},
    "influenza": {"name": "Influenza (Flu)", "cardinal": ["fever", "body_ache", "fatigue"], "common": ["cough", "headache", "chills", "sore_throat"], "advice": "Rest, hydrate, and consider antiviral medications if started within 48 hours."},
    "covid19": {"name": "COVID-19", "cardinal": ["fever", "cough", "loss_smell"], "common": ["fatigue", "shortness_breath", "sore_throat", "body_ache", "headache"], "advice": "Isolate and get tested. Monitor oxygen levels."},
    "migraine": {"name": "Migraine", "cardinal": ["headache", "sensitivity_light"], "common": ["nausea", "vomiting", "dizziness"], "advice": "Rest in a dark, quiet room. Consider OTC pain relievers."},
    "gastroenteritis": {"name": "Gastroenteritis (Stomach Flu)", "cardinal": ["diarrhea", "vomiting", "abdominal_pain"], "common": ["nausea", "fever", "fatigue", "loss_appetite"], "advice": "Stay hydrated with fluids and electrolytes (ORS)."},
    "uti": {"name": "Urinary Tract Infection (UTI)", "cardinal": ["burning_urination", "frequent_urination"], "common": ["abdominal_pain", "fever", "back_pain"], "advice": "See a healthcare provider for urine testing and antibiotics."},
    "diabetes_type2": {"name": "Type 2 Diabetes (screening suggested)", "cardinal": ["frequent_urination", "excessive_thirst"], "common": ["fatigue", "blurred_vision", "weight_loss"], "advice": "Get blood sugar testing (HbA1c, fasting glucose)."},
    "asthma": {"name": "Asthma", "cardinal": ["shortness_breath", "wheezing"], "common": ["cough", "chest_pain"], "advice": "Use prescribed rescue inhaler. Identify and avoid triggers."},
    "strep_throat": {"name": "Strep Throat", "cardinal": ["sore_throat", "fever"], "common": ["headache", "nausea", "rash"], "advice": "See a doctor for a strep test. Antibiotics are needed if positive."},
    "pneumonia": {"name": "Pneumonia", "cardinal": ["fever", "cough", "shortness_breath"], "common": ["chest_pain", "fatigue", "chills"], "advice": "Seek medical evaluation promptly. May require antibiotics."},
}

SYMPTOM_LABELS = {k: k.replace("_", " ") for k in SYMPTOMS.keys()}

RED_FLAGS = [
    {"id": "cardiac", "patterns": ["chest pain", "chest pressure", "chest tightness", "pain in chest", "crushing chest", "pain radiating to arm"], "message": "⚠️ Your symptoms may indicate a cardiac emergency. Call 911 immediately.", "severity": "emergency"},
    {"id": "breathing", "patterns": ["can't breathe", "cannot breathe", "severe shortness of breath", "choking", "suffocating"], "message": "⚠️ Severe breathing difficulty is a medical emergency. Call 911 immediately.", "severity": "emergency"},
    {"id": "stroke", "patterns": ["face drooping", "arm weakness", "slurred speech", "sudden numbness", "weakness on one side", "can't speak"], "message": "⚠️ These may be stroke symptoms (FAST). Call 911 immediately.", "severity": "emergency"},
    {"id": "suicidal", "patterns": ["suicidal", "kill myself", "end my life", "want to die", "hurt myself"], "message": "🆘 Your safety matters. Please call 988 (Suicide & Crisis Lifeline) or 911 immediately.", "severity": "crisis"},
]

# ---------------------------------------------------------------------------
# NLP Functions (Rule-Based)
# ---------------------------------------------------------------------------
NEGATIONS = ["no ", "not ", "without", "don't have", "dont have", "don't feel", "dont feel", "no longer", "never", "isn't", "aren't", "haven't", "stopped", "free of", "absence of"]

def extract_symptoms(text):
    text_lower = text.lower()
    found = {}
    for symptom_id, aliases in SYMPTOMS.items():
        for alias in aliases:
            pattern = r"\b" + re.escape(alias) + r"\b"
            for match in re.finditer(pattern, text_lower):
                start = match.start()
                prefix = text_lower[max(0, start - 40):start]
                if not any(neg in prefix for neg in NEGATIONS):
                    found[symptom_id] = True
                    break
            if symptom_id in found: break
    return list(found.keys())

def detect_red_flags(text):
    text_lower = text.lower()
    matches = []
    for flag in RED_FLAGS:
        if any(pattern in text_lower for pattern in flag["patterns"]):
            matches.append(flag)
    return matches

def score_conditions(symptoms):
    if not symptoms: return []
    scores = []
    for cond_id, cond in CONDITIONS.items():
        cardinal_set = set(cond["cardinal"])
        common_set = set(cond["common"])
        symp_set = set(symptoms)
        
        cm = cardinal_set & symp_set
        om = common_set & symp_set
        if not cm and not om: continue
        
        cs = len(cm) / max(len(cardinal_set), 1) * 0.7
        os = len(om) / max(len(common_set), 1) * 0.3
        total = cs + os
        
        scores.append({
            "id": cond_id, "name": cond["name"], "score": round(total, 3),
            "confidence_pct": round(total * 100, 1),
            "cardinal_matched": [SYMPTOM_LABELS.get(s, s) for s in cm],
            "common_matched": [SYMPTOM_LABELS.get(s, s) for s in om],
            "advice": cond["advice"],
        })
    scores.sort(key=lambda x: x["score"], reverse=True)
    return scores

def build_rule_based_response(message_text, accumulated_symptoms):
    red_flags = detect_red_flags(message_text)
    if red_flags:
        return {"type": "emergency", "text": red_flags[0]["message"], "severity": red_flags[0]["severity"], "disclaimer": True}

    new_symptoms = extract_symptoms(message_text)
    all_symptoms = list(set(accumulated_symptoms + new_symptoms))
    scores = score_conditions(all_symptoms)

    if not scores:
        if new_symptoms:
            return {"type": "explore", "text": "I noted your symptoms but couldn't match them to a specific condition. Could you describe how long you've had them?", "symptoms": [SYMPTOM_LABELS.get(s, s) for s in new_symptoms]}
        return {"type": "clarify", "text": "I couldn't identify specific symptoms. Try describing what you're feeling."}

    top = scores[0]
    if top["score"] >= 0.55:
        return {"type": "diagnosis", "text": f"Based on your symptoms, you may have **{top['name']}** (approx. {top['confidence_pct']}% match).", "diagnosis": top, "alternatives": scores[1:3], "symptoms": [SYMPTOM_LABELS.get(s, s) for s in all_symptoms], "disclaimer": True}
    
    if top["score"] >= 0.3:
        return {"type": "followup", "text": f"Your symptoms could be consistent with **{top['name']}**. To refine this, do you also experience other related symptoms?", "diagnosis": top, "alternatives": scores[1:2], "symptoms": [SYMPTOM_LABELS.get(s, s) for s in all_symptoms], "disclaimer": True}

    return {"type": "explore", "text": "I'm considering a few possibilities. Could you tell me more — do you have any fever, pain, or breathing discomfort?", "partial": scores[:3], "symptoms": [SYMPTOM_LABELS.get(s, s) for s in all_symptoms]}


# ---------------------------------------------------------------------------
# AI Engine (Google Gemini)
# ---------------------------------------------------------------------------
def build_gemini_response(message_text, history):
    """Calls Google Gemini API for a conversational response."""
    
    # Format history for Gemini
    contents = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    
    # Add current message
    contents.append({"role": "user", "parts": [{"text": message_text}]})

    system_prompt = (
        "You are MediBot, an AI medical assistant. Your goal is to help users understand their symptoms. "
        "Ask clarifying questions one by one to narrow down the condition. "
        "If you suspect a diagnosis, state it clearly but emphasize it is not a medical diagnosis. "
        "Keep responses concise, empathetic, and under 100 words. "
        "Always remind users to seek professional medical advice for serious issues."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 150}
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
        data = res.json()
        ai_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        
        if not ai_text:
            return {"type": "error", "text": "The AI engine returned an empty response. Please try the Rule-Based engine."}
            
        return {
            "type": "ai_response",
            "text": ai_text.strip(),
            "disclaimer": True
        }
    except Exception as e:
        return {
            "type": "error",
            "text": "⚠️ The AI engine is currently unavailable or rate-limited. Please switch back to the Rule-Based engine."
        }


# ---------------------------------------------------------------------------
# Database Helpers (Same as before)
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL)
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS conversations (session_id VARCHAR(64) PRIMARY KEY, created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW());")
            cur.execute("CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, session_id VARCHAR(64) NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE, role VARCHAR(16) NOT NULL, content TEXT NOT NULL, symptoms JSONB, diagnosis JSONB, created_at TIMESTAMPTZ DEFAULT NOW());")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);")
        conn.commit()
    finally:
        conn.close()

def upsert_conversation(session_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("INSERT INTO conversations (session_id, updated_at) VALUES (%s, NOW()) ON CONFLICT (session_id) DO UPDATE SET updated_at = NOW();", (session_id,))
    db.commit()

def save_message(session_id, role, content, symptoms=None, diagnosis=None):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("INSERT INTO messages (session_id, role, content, symptoms, diagnosis) VALUES (%s, %s, %s, %s, %s);",
                    (session_id, role, content, json.dumps(symptoms) if symptoms else None, json.dumps(diagnosis) if diagnosis else None))
    db.commit()

def get_accumulated_symptoms(session_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT content FROM messages WHERE session_id = %s AND role = 'user' ORDER BY created_at ASC;", (session_id,))
        rows = cur.fetchall()
    accumulated = []
    for row in rows:
        accumulated.extend(extract_symptoms(row["content"]))
    return list(set(accumulated))

def load_history(session_id, limit=20):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT role, content, symptoms, diagnosis, created_at FROM messages WHERE session_id = %s ORDER BY created_at ASC LIMIT %s;", (session_id, limit))
        rows = cur.fetchall()
    return [{"role": r["role"], "content": r["content"], "symptoms": r["symptoms"], "diagnosis": r["diagnosis"], "timestamp": r["created_at"].isoformat() if r["created_at"] else None} for r in rows]

def reset_session(session_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("DELETE FROM messages WHERE session_id = %s;", (session_id,))
        cur.execute("INSERT INTO conversations (session_id, updated_at) VALUES (%s, NOW()) ON CONFLICT (session_id) DO UPDATE SET updated_at = NOW();", (session_id,))
    db.commit()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_file(os.path.join(APP_DIR, "index.html"))

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True) or {}
    session_id = data.get("session_id") or str(uuid.uuid4())
    message = (data.get("message") or "").strip()
    engine = data.get("engine", "rule") # "rule" or "ai"

    if not message: return jsonify({"error": "Message is required"}), 400

    upsert_conversation(session_id)
    save_message(session_id, "user", message)

    # SAFETY FEATURE: Always check for red flags regardless of engine
    if detect_red_flags(message):
        response = build_rule_based_response(message, [])
    else:
        if engine == "ai" and GEMINI_API_KEY:
            # Pass recent history to AI for context
            history = load_history(session_id, limit=10)
            response = build_gemini_response(message, history)
        else:
            # Fallback to rule-based if AI is selected but no API key is set
            accumulated = get_accumulated_symptoms(session_id)
            response = build_rule_based_response(message, accumulated)

    save_message(session_id, "bot", response["text"], symptoms=response.get("symptoms"), diagnosis=response.get("diagnosis"))
    return jsonify({"session_id": session_id, "response": response})

@app.route("/api/history/<session_id>", methods=["GET"])
def history(session_id):
    return jsonify({"session_id": session_id, "messages": load_history(session_id)})

@app.route("/api/reset", methods=["POST"])
def reset():
    data = request.get_json(force=True) or {}
    session_id = data.get("session_id")
    if not session_id: return jsonify({"error": "session_id required"}), 400
    reset_session(session_id)
    return jsonify({"status": "reset", "session_id": session_id})

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
else:
    try: init_db()
    except Exception as e: app.logger.error(f"DB init failed: {e}")
