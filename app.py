import os
import logging
import requests
from flask import Flask, request, jsonify, send_file

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
    """Primary route for the Gemini-powered AI diagnostic chat using direct REST API."""
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

    # 2. Call Gemini via Direct REST API
    formatted_history = []
    started_with_user = False
    
    for msg in history:
        role = 'user' if msg['role'] == 'user' else 'model'
        
        # Gemini API requires the conversation history to start with a 'user' message
        if not started_with_user and role == 'model':
            continue
        started_with_user = True
        
        formatted_history.append({
            "role": role, 
            "parts": [{"text": msg['content']}]
        })
        
    system_instruction = (
        "You are a professional medical triage assistant. Analyze the symptoms provided by the user. "
        "Give a clear, structured assessment including an urgency level (Emergency, See a Doctor, or Home Care), "
        "possible conditions, and recommended guidance. Be concise and use Markdown formatting."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": formatted_history,
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {"temperature": 0.2}
    }

    try:
        # Added a timeout so the server doesn't hang indefinitely 
        response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=20)
        
        # Robust JSON parsing: Prevents the "Expecting value: line 1 column 1" crash
        # when Google returns an HTML error page (e.g., 502 Bad Gateway)
        try:
            result = response.json()
        except ValueError:
            logger.error(f"Non-JSON response from API. Status: {response.status_code}, Body: {response.text[:200]}")
            return jsonify({
                "error": f"The AI server returned an invalid response (Status {response.status_code}).", 
                "can_fallback": True
            }), 503
        
        # Handle valid JSON but with HTTP error status (e.g., Quota Exceeded, 403 Forbidden)
        if response.status_code != 200:
            error_msg = result.get('error', {}).get('message', 'Unknown Gemini API Error')
            logger.error(f"Gemini REST API Error: {error_msg}")
            return jsonify({
                "error": f"API Error: {error_msg}", 
                "can_fallback": True
            }), 503
        
        # Extract success payload
        if 'candidates' in result and len(result['candidates']) > 0:
            result_text = result['candidates'][0]['content']['parts'][0]['text']
            
            # Save to Case Memory
            db.save_case(case_hash, user_text, result_text, "unknown", "ai")
            
            return jsonify({"text": result_text, "engine": "ai"})
        else:
            logger.error(f"Unexpected JSON structure: {result}")
            return jsonify({
                "error": "Received an empty or unrecognizable response from the AI.", 
                "can_fallback": True
            }), 503

    # Catch timeouts and network drops safely
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {str(e)}")
        return jsonify({
            "error": "Network timeout or connection error while contacting the AI Engine.", 
            "can_fallback": True
        }), 503
    except Exception as e:
        logger.error(f"Unexpected Error: {str(e)}")
        return jsonify({
            "error": f"An unexpected error occurred: {str(e)}", 
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


