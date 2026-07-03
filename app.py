import os
import logging
from flask import Flask, request, jsonify, send_file
from google import genai

import db
import engine

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Fetch Gemini API Key
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

@app.route('/')
def index():
    """Serves the frontend."""
    return send_file('index.html')

@app.route('/api/chat/ai', methods=['POST'])
def chat_ai():
    """Primary route for the Gemini-powered AI diagnostic chat."""
    if not GEMINI_API_KEY:
        return jsonify({
            "error": "Gemini API key is not configured on this server.", 
            "can_fallback": True
        }), 503

    data = request.json
    history = data.get("history", [])
    if not history:
        return jsonify({"error": "No chat history provided.", "can_fallback": False}), 400

    user_text = history[-1]["content"]
    
    # 1. Check Case Memory
    case_hash = db.hash_case(user_text)
    cached = db.get_cached_case(case_hash)
    if cached:
        logger.info(f"Cache hit for case: {case_hash}")
        return jsonify({"text": cached[0], "tier": cached[1], "engine": "cache"})

    # 2. Call Gemini
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Construct system prompt and history
        prompt = (
            "You are a professional medical triage assistant. Analyze the symptoms provided by the user. "
            "Give a clear, structured assessment including an urgency level (Emergency, See a Doctor, or Home Care), "
            "possible conditions, and recommended guidance. Be concise and use Markdown formatting.\n\n"
        )
        for msg in history:
            prompt += f"{msg['role'].capitalize()}: {msg['content']}\n"
        prompt += "Assistant: "

        # Changed to gemini-1.5-flash to fix the 403 Permission/Availability Error
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )

        result_text = response.text
        
        # Save to Case Memory
        db.save_case(case_hash, user_text, result_text, "unknown", "ai")
        
        return jsonify({"text": result_text, "engine": "ai"})

    except Exception as e:
        error_msg = str(e)
        
        # Clean up the raw API errors for better user experience
        if "403" in error_msg:
            friendly_error = "Access Denied (403). Your Gemini API key is either restricted in your region or lacks permissions for this model."
        elif "404" in error_msg:
            friendly_error = "Model not found (404). The AI model is currently unavailable."
        elif hasattr(e, 'message'):
            friendly_error = e.message
        else:
            friendly_error = error_msg
            
        logger.error(f"Gemini Engine Failed: {error_msg}")
        
        return jsonify({
            "error": friendly_error, 
            "can_fallback": True
        }), 503

@app.route('/api/chat/builtin', methods=['POST'])
def chat_builtin():
    """Fallback route handling structured form data for the built-in rule-based engine."""
    data = request.json
    
    symptoms = data.get("symptoms", [])
    severity = data.get("severity", "")
    duration = data.get("duration", "")
    history_text = data.get("history", "")

    # Construct a natural language string that engine.py's Regex/NLP can parse seamlessly
    symptoms_str = ", ".join(symptoms) if symptoms else "none"
    constructed_text = f"Symptoms: {symptoms_str}. "
    
    if severity:
        constructed_text += f"Severity is {severity} out of 10. "
    if duration:
        constructed_text += f"It has been going on for {duration}. "
    if history_text:
        constructed_text += f"Medical history: {history_text}. "

    # 1. Process via Built-in Engine
    report = engine.build_report(constructed_text)
    
    # 2. Save to Case Memory
    case_hash = db.hash_case(constructed_text)
    db.save_case(case_hash, constructed_text, report["report_text"], report["tier"], "engine")

    return jsonify({
        "text": report["report_text"],
        "tier": report["tier"],
        "engine": "engine"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
