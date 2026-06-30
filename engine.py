"""
engine.py
─────────────────────────────────────────────────────────────────────────────
Built-in Rule-Based Diagnostic Engine.

This module is the offline / fail-safe brain of the system. Whenever the
primary online AI engine is unreachable, rate-limited, unconfigured, or has
exceeded its daily usage allowance, control is handed over to the logic in
this file so that the visitor always receives a complete, professional
assessment instead of an error message.

The engine works in three stages:
    1. Intake  -> extract symptoms, severity, duration and red-flag phrases
                  from the visitor's own words.
    2. Reasoning -> score a curated knowledge base of common conditions
                  against the extracted symptoms and decide an urgency tier.
    3. Reporting -> render a structured, professional diagnosis report in
                  the same plain/bold text style used by the online engine,
                  so the chat interface displays it identically.

This is an educational triage aid, not a certified medical device.
─────────────────────────────────────────────────────────────────────────────
"""

import re
from dataclasses import dataclass, field

# ──────────────────────────────────────────────────────────────────────────
# 1. SYMPTOM LEXICON
#    Maps an internal symptom id -> the phrases a visitor might type.
# ──────────────────────────────────────────────────────────────────────────
SYMPTOM_LEXICON = {
    "fever":                ["fever", "high temperature", "running a temperature", "hot body", "rigors", "feverish"],
    "chills":                ["chills", "shivering", "cold sweats"],
    "headache":              ["headache", "head pain", "pounding head", "head is aching"],
    "body_ache":             ["body ache", "body pains", "muscle pain", "muscle ache", "joint pain", "aching all over"],
    "fatigue":                ["fatigue", "tiredness", "feeling weak", "exhausted", "no energy", "weakness"],
    "cough":                  ["cough", "coughing"],
    "sore_throat":            ["sore throat", "throat pain", "painful swallowing", "scratchy throat"],
    "runny_nose":             ["runny nose", "nasal discharge", "catarrh"],
    "nasal_congestion":       ["blocked nose", "stuffy nose", "nasal congestion", "congested nose"],
    "sneezing":               ["sneezing", "sneeze"],
    "shortness_of_breath":    ["shortness of breath", "difficulty breathing", "breathless", "can't breathe", "cant breathe", "struggling to breathe", "out of breath"],
    "chest_pain":             ["chest pain", "chest tightness", "chest discomfort", "pain in my chest"],
    "wheezing":               ["wheezing", "whistling sound when breathing"],
    "palpitations":           ["palpitations", "racing heart", "heart racing", "irregular heartbeat", "pounding heart"],
    "nausea":                 ["nausea", "feel like vomiting", "queasy", "feeling sick"],
    "vomiting":               ["vomit", "vomiting", "throwing up"],
    "diarrhea":               ["diarrhea", "diarrhoea", "loose stool", "watery stool", "frequent stooling", "stooling"],
    "constipation":           ["constipation", "can't pass stool", "difficulty passing stool"],
    "abdominal_pain":         ["abdominal pain", "stomach pain", "stomach ache", "belly pain", "tummy pain", "stomachache"],
    "loss_of_appetite":       ["loss of appetite", "not eating", "no appetite", "don't feel like eating"],
    "heartburn":              ["heartburn", "acid reflux", "burning in my chest after eating", "indigestion"],
    "dizziness":              ["dizziness", "dizzy", "lightheaded", "feeling faint"],
    "rash":                   ["rash", "skin eruption", "hives", "red spots on skin", "skin bumps"],
    "itching":                ["itching", "itchy skin", "skin itches"],
    "ear_pain":               ["ear pain", "earache", "pain in my ear"],
    "eye_redness":            ["red eyes", "eye redness", "watery eyes", "itchy eyes", "eye discharge"],
    "burning_urination":      ["burning urination", "pain when urinating", "burning when i pee", "burning sensation when peeing"],
    "frequent_urination":     ["frequent urination", "urinating often", "peeing a lot", "going to toilet frequently to urinate"],
    "night_sweats":           ["night sweats", "sweating at night", "excessive sweating"],
    "weight_loss":            ["weight loss", "losing weight", "lost weight unintentionally"],
    "jaundice":               ["yellow eyes", "jaundice", "yellowish skin"],
    "confusion":              ["confusion", "disoriented", "difficulty thinking clearly"],
    "anxiety_symptoms":       ["anxious", "anxiety", "panic attack", "panicking", "feeling on edge"],
    "insomnia":               ["insomnia", "can't sleep", "trouble sleeping", "not sleeping well"],
    "dental_pain":            ["tooth pain", "toothache", "dental pain"],
    "swollen_glands":         ["swollen glands", "swollen lymph nodes", "swelling in my neck"],
    "back_pain":              ["back pain", "lower back pain", "lumbar pain"],
    "joint_swelling":         ["swollen joint", "joint swelling", "swollen knee", "swollen ankle"],
    "bleeding":               ["bleeding", "blood loss"],
    "blurred_vision":         ["blurred vision", "blurry vision", "difficulty seeing clearly"],
}

# ──────────────────────────────────────────────────────────────────────────
# 2. RED-FLAG / EMERGENCY PATTERNS
#    Any match here forces the EMERGENCY tier regardless of scoring below.
# ──────────────────────────────────────────────────────────────────────────
RED_FLAGS = [
    ("severe chest pain radiating to the arm or jaw, or chest pain with sweating and breathlessness",
     ["chest pain" , "radiating", "left arm"], "chest_pain_cardiac"),
    ("sudden facial drooping, slurred speech, or one-sided weakness (possible stroke)",
     ["face drooping", "slurred speech", "one side of my body", "can't move my arm", "facial droop"], "stroke"),
    ("severe or worsening difficulty breathing",
     ["can't breathe", "cant breathe", "severe difficulty breathing", "gasping for air", "turning blue", "lips turning blue"], "respiratory_distress"),
    ("thoughts of suicide or self-harm",
     ["suicidal", "want to die", "kill myself", "end my life", "harm myself", "ending it all"], "self_harm"),
    ("uncontrolled or heavy bleeding",
     ["uncontrolled bleeding", "won't stop bleeding", "heavy bleeding", "bleeding a lot"], "severe_bleeding"),
    ("loss of consciousness or unresponsiveness",
     ["unconscious", "unresponsive", "passed out", "fainted and not waking up"], "unconscious"),
    ("signs of a severe allergic reaction (throat closing, facial swelling, widespread hives with breathing difficulty)",
     ["throat closing", "swelling of my face", "swelling of my throat", "anaphylaxis", "throat is swelling"], "anaphylaxis"),
    ("an active seizure or convulsion",
     ["seizure", "convulsion", "convulsing", "fitting"], "seizure"),
    ("a rigid, severely painful abdomen",
     ["rigid abdomen", "abdomen is hard", "unbearable stomach pain"], "acute_abdomen"),
    ("suspected poisoning or overdose",
     ["poisoning", "overdose", "swallowed chemical", "took too many tablets"], "poisoning"),
]

# ──────────────────────────────────────────────────────────────────────────
# 3. CONDITION KNOWLEDGE BASE
#    weight: 1 = supportive, 2 = typical, 3 = hallmark symptom
#    tier:   "green" = home care, "yellow" = see a doctor, "red" = emergency
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Condition:
    name: str
    category: str
    symptoms: dict
    tier: str
    summary: str
    guidance: list = field(default_factory=list)


CONDITIONS = [
    Condition(
        "Malaria", "Infectious Disease",
        {"fever": 3, "chills": 3, "headache": 2, "body_ache": 2, "fatigue": 2, "nausea": 1, "vomiting": 1},
        "yellow",
        "A mosquito-borne infection common in tropical regions, typically presenting with cyclical fever, chills and body aches.",
        ["Seek a malaria parasite test (RDT or microscopy) at a clinic as soon as possible.",
         "Stay hydrated and rest while awaiting evaluation.",
         "Use insecticide-treated nets to prevent further mosquito bites."],
    ),
    Condition(
        "Typhoid Fever", "Infectious Disease",
        {"fever": 3, "headache": 2, "abdominal_pain": 2, "loss_of_appetite": 2, "fatigue": 1, "constipation": 1, "diarrhea": 1},
        "yellow",
        "A bacterial infection usually contracted from contaminated food or water, marked by a sustained step-wise fever and abdominal discomfort.",
        ["A blood culture or Widal test is recommended to confirm diagnosis.",
         "Drink only clean, boiled or treated water.",
         "Avoid self-medicating with antibiotics; a clinician must confirm the diagnosis first."],
    ),
    Condition(
        "Common Cold", "Respiratory",
        {"runny_nose": 3, "nasal_congestion": 2, "sneezing": 2, "sore_throat": 1, "cough": 1, "fatigue": 1},
        "green",
        "A mild, self-limiting viral infection of the upper airway.",
        ["Rest and stay well hydrated.",
         "Warm fluids and steam inhalation may ease congestion.",
         "Over-the-counter saline sprays can relieve nasal stuffiness."],
    ),
    Condition(
        "Influenza (Flu)", "Respiratory",
        {"fever": 2, "body_ache": 3, "fatigue": 2, "cough": 2, "headache": 1, "sore_throat": 1, "chills": 1},
        "yellow",
        "A viral respiratory illness with a more abrupt onset and more pronounced body aches than the common cold.",
        ["Rest, fluids and fever-reducing measures are key.",
         "Seek care promptly if breathing becomes difficult or fever persists beyond three days."],
    ),
    Condition(
        "Acute Bronchitis", "Respiratory",
        {"cough": 3, "fatigue": 1, "sore_throat": 1, "wheezing": 1, "chest_pain": 1},
        "yellow",
        "Inflammation of the airways, often following a viral cold, causing a persistent cough sometimes with mucus.",
        ["Keep airways moist with steam and fluids.",
         "See a doctor if the cough lasts beyond two weeks or you cough up blood."],
    ),
    Condition(
        "Pneumonia (Possible)", "Respiratory",
        {"fever": 2, "cough": 2, "shortness_of_breath": 3, "chest_pain": 2, "fatigue": 1},
        "red",
        "A lung infection that can become serious quickly, especially when breathing difficulty is present.",
        ["This combination of symptoms warrants prompt in-person medical evaluation, ideally the same day.",
         "A chest examination or X-ray may be required."],
    ),
    Condition(
        "Asthma Exacerbation", "Respiratory",
        {"shortness_of_breath": 3, "wheezing": 3, "cough": 1, "chest_pain": 1},
        "yellow",
        "A flare-up of airway narrowing causing wheezing and breathlessness.",
        ["Use a prescribed reliever inhaler if available.",
         "Seek urgent care if symptoms do not ease after using an inhaler."],
    ),
    Condition(
        "Migraine", "Neurological",
        {"headache": 3, "nausea": 1, "dizziness": 1, "blurred_vision": 1},
        "green",
        "A recurring, often one-sided headache disorder that can be accompanied by nausea and visual disturbance.",
        ["Rest in a quiet, dark room.",
         "Stay hydrated and avoid known triggers (bright light, certain foods, stress).",
         "See a doctor if this is the worst headache of your life, or it is sudden and severe."],
    ),
    Condition(
        "Tension Headache", "Neurological",
        {"headache": 3, "fatigue": 1, "back_pain": 1},
        "green",
        "A common headache often related to stress, poor posture or eye strain.",
        ["Rest, gentle neck stretches and adequate hydration usually help.",
         "Persistent or worsening headaches should be reviewed by a doctor."],
    ),
    Condition(
        "Gastroenteritis / Food Poisoning", "Digestive",
        {"diarrhea": 3, "vomiting": 2, "abdominal_pain": 2, "nausea": 2, "fever": 1},
        "yellow",
        "Inflammation of the stomach and intestines, commonly from contaminated food or water, causing diarrhea and vomiting.",
        ["Oral rehydration solution is the priority to prevent dehydration.",
         "Seek care if there is blood in the stool, high fever, or symptoms beyond 2 days."],
    ),
    Condition(
        "Acid Reflux / Gastritis", "Digestive",
        {"heartburn": 3, "abdominal_pain": 1, "nausea": 1, "loss_of_appetite": 1},
        "green",
        "Irritation of the stomach lining or reflux of stomach acid, often related to diet or stress.",
        ["Avoid spicy, fatty or acidic foods and large meals before bed.",
         "See a doctor if symptoms persist beyond two weeks or you notice dark stool."],
    ),
    Condition(
        "Urinary Tract Infection", "Genitourinary",
        {"burning_urination": 3, "frequent_urination": 2, "abdominal_pain": 1, "fever": 1},
        "yellow",
        "A bacterial infection of the urinary tract, more common in women, causing painful or frequent urination.",
        ["Increase water intake and seek a urine test for confirmation.",
         "See a doctor promptly if fever or back/flank pain develops, which may indicate a kidney infection."],
    ),
    Condition(
        "Allergic Rhinitis / Mild Allergy", "Immunologic",
        {"sneezing": 2, "runny_nose": 2, "itching": 2, "eye_redness": 2, "nasal_congestion": 1},
        "green",
        "An allergic response to environmental triggers such as dust, pollen, or pet dander.",
        ["Identify and avoid the suspected trigger where possible.",
         "Antihistamine medication (as advised by a pharmacist) may help with symptom relief."],
    ),
    Condition(
        "Skin Rash / Dermatitis", "Dermatologic",
        {"rash": 3, "itching": 2, "eye_redness": 1},
        "green",
        "Skin irritation that may result from contact with an irritant, infection, or allergy.",
        ["Keep the area clean and dry, and avoid scratching.",
         "See a doctor if the rash spreads rapidly, blisters, or is accompanied by fever."],
    ),
    Condition(
        "Conjunctivitis (Eye Infection)", "Ophthalmologic",
        {"eye_redness": 3, "itching": 1},
        "green",
        "Inflammation of the eye's outer membrane, often from infection or allergy, causing redness and discharge.",
        ["Avoid touching or rubbing the eyes and wash hands frequently.",
         "See a doctor if vision is affected or pain is significant."],
    ),
    Condition(
        "Ear Infection (Otitis Media)", "ENT",
        {"ear_pain": 3, "fever": 1},
        "yellow",
        "Infection or inflammation of the middle ear, common after a cold.",
        ["Pain relief and warm compresses can help in the short term.",
         "See a doctor if pain is severe, persists beyond 2 days, or there is discharge from the ear."],
    ),
    Condition(
        "Sinusitis", "ENT",
        {"nasal_congestion": 2, "headache": 1, "sore_throat": 1, "fever": 1},
        "green",
        "Inflammation of the sinus passages, often following a cold, causing facial pressure and congestion.",
        ["Steam inhalation and saline rinses can offer relief.",
         "See a doctor if symptoms persist beyond ten days or fever is high."],
    ),
    Condition(
        "Strep Throat / Tonsillitis", "ENT",
        {"sore_throat": 3, "fever": 2, "swollen_glands": 2, "loss_of_appetite": 1},
        "yellow",
        "A throat infection that may be bacterial, sometimes requiring antibiotic treatment.",
        ["A throat swab can confirm whether antibiotics are needed.",
         "Warm salt-water gargles can ease discomfort in the meantime."],
    ),
    Condition(
        "Dental Infection / Toothache", "Dental",
        {"dental_pain": 3, "swollen_glands": 1, "fever": 1},
        "yellow",
        "Pain originating from a tooth or gum, which may indicate decay, infection, or abscess.",
        ["See a dentist promptly, especially if there is facial swelling or fever.",
         "Warm salt-water rinses may offer temporary relief."],
    ),
    Condition(
        "Anxiety / Panic Episode", "Mental Health",
        {"anxiety_symptoms": 3, "palpitations": 2, "shortness_of_breath": 1, "dizziness": 1, "insomnia": 1},
        "yellow",
        "A surge of intense worry or fear that can produce physical symptoms resembling a medical emergency.",
        ["Slow, controlled breathing and grounding techniques can help during an episode.",
         "Speak with a counsellor or doctor, particularly if these episodes are frequent or distressing.",
         "If chest pain or breathlessness is severe or new, seek medical evaluation to rule out a physical cause first."],
    ),
    Condition(
        "Musculoskeletal Back Pain", "Musculoskeletal",
        {"back_pain": 3, "body_ache": 1},
        "green",
        "Pain arising from muscles, ligaments or joints of the back, often related to posture or strain.",
        ["Gentle movement, rest from strenuous activity, and warm compresses can help.",
         "See a doctor if pain radiates down a leg, or there is numbness or weakness."],
    ),
    Condition(
        "Joint Inflammation (Arthralgia)", "Musculoskeletal",
        {"joint_swelling": 3, "body_ache": 1, "fever": 1},
        "yellow",
        "Swelling or pain in one or more joints, which can have infectious, inflammatory or traumatic causes.",
        ["Rest and elevate the affected joint and avoid weight-bearing if painful.",
         "See a doctor for assessment, especially if redness or warmth is present."],
    ),
    Condition(
        "Dehydration", "General",
        {"dizziness": 2, "fatigue": 2, "headache": 1, "nausea": 1},
        "yellow",
        "Insufficient body fluid, often from inadequate intake, heat, vomiting, or diarrhea.",
        ["Rehydrate with water or oral rehydration solution in small frequent sips.",
         "Seek care urgently if unable to keep fluids down or experiencing confusion."],
    ),
    Condition(
        "Possible Hepatic / Liver Concern", "Digestive",
        {"jaundice": 3, "fatigue": 1, "loss_of_appetite": 1, "abdominal_pain": 1},
        "red",
        "Yellowing of the eyes or skin can indicate a liver problem that needs urgent assessment.",
        ["This finding requires prompt evaluation with liver function tests.",
         "Avoid alcohol and unnecessary medication until assessed."],
    ),
]


# ──────────────────────────────────────────────────────────────────────────
# 4. INTAKE — extracting structured signal from free text
# ──────────────────────────────────────────────────────────────────────────
def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def extract_symptoms(text: str) -> dict:
    """Return {symptom_id: matched_phrase} for every symptom phrase found."""
    norm = _normalize(text)
    found = {}
    for symptom_id, phrases in SYMPTOM_LEXICON.items():
        for phrase in phrases:
            if phrase in norm:
                found[symptom_id] = phrase
                break
    return found


def extract_red_flags(text: str) -> list:
    norm = _normalize(text)
    hits = []
    for description, phrases, _key in RED_FLAGS:
        for phrase in phrases:
            if phrase in norm:
                hits.append(description)
                break
    return hits


def extract_severity(text: str):
    norm = _normalize(text)
    m = re.search(r"(\d{1,2})\s*(?:/|out of)\s*10", norm)
    if m:
        val = int(m.group(1))
        return min(val, 10)
    m = re.search(r"severity[^0-9]{0,10}(\d{1,2})", norm)
    if m:
        return min(int(m.group(1)), 10)
    return None


def extract_duration(text: str):
    norm = _normalize(text)
    m = re.search(r"(?:for|since|about)?\s*(\d+)\s*(hour|hours|day|days|week|weeks|month|months)", norm)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    if "today" in norm or "this morning" in norm:
        return "today"
    if "yesterday" in norm:
        return "since yesterday"
    return None


# ──────────────────────────────────────────────────────────────────────────
# 5. REASONING — score conditions against extracted symptoms
# ──────────────────────────────────────────────────────────────────────────
def score_conditions(found_symptoms: dict) -> list:
    """Return a ranked list of (Condition, confidence_pct, matched_ids)."""
    if not found_symptoms:
        return []

    results = []
    found_ids = set(found_symptoms.keys())
    for cond in CONDITIONS:
        cond_ids = set(cond.symptoms.keys())
        matched = found_ids & cond_ids
        if not matched:
            continue
        matched_weight = sum(cond.symptoms[s] for s in matched)
        total_weight = sum(cond.symptoms.values())
        coverage_of_condition = matched_weight / total_weight  # how much of the condition's profile is explained
        coverage_of_report = len(matched) / max(len(found_ids), 1)  # how much of what user said is explained
        confidence = round((0.7 * coverage_of_condition + 0.3 * coverage_of_report) * 100)
        if confidence < 20:
            continue
        results.append((cond, confidence, matched))

    results.sort(key=lambda r: r[1], reverse=True)
    return results[:4]


def determine_tier(red_flags, severity, top_matches):
    if red_flags:
        return "red"
    if severity is not None and severity >= 8:
        return "yellow" if not top_matches or top_matches[0][0].tier != "red" else "red"
    if top_matches:
        worst = max((m[0].tier for m in top_matches), key=lambda t: {"green": 0, "yellow": 1, "red": 2}[t])
        return worst
    return "green"


# ──────────────────────────────────────────────────────────────────────────
# 6. REPORTING — render the final professional report text
# ──────────────────────────────────────────────────────────────────────────
TIER_LABELS = {
    "red":    "🔴 EMERGENCY — Seek Immediate Care",
    "yellow": "🟡 SEE A DOCTOR — Within 24–72 Hours",
    "green":  "🟢 HOME CARE — Self-Manageable",
}


def _format_symptom_list(found_symptoms: dict) -> str:
    pretty = [sid.replace("_", " ") for sid in found_symptoms.keys()]
    return ", ".join(sorted(pretty))


def build_clarifying_question(found_symptoms: dict) -> str:
    known = f" So far I have noted: {_format_symptom_list(found_symptoms)}." if found_symptoms else ""
    return (
        "**Built-in Diagnostic Engine — Intake**\n"
        "Thank you for sharing that. To complete a reliable assessment I need a little more detail."
        f"{known}\n\n"
        "Please tell me:\n"
        "• When did this start, and has it been getting better, worse, or staying the same?\n"
        "• On a scale of 1 to 10, how severe is it?\n"
        "• Is there anything that makes it better or worse?\n"
        "• Do you have any relevant medical history (e.g. existing conditions, recent travel, medication)?"
    )


def build_report(raw_text: str, history_text: str = "") -> dict:
    """
    Main entry point. Analyzes the visitor's case text (optionally combined
    with prior turns in `history_text` for added context) and returns:
        {
          "report_text": str,   # ready to send to the client
          "tier": "red" | "yellow" | "green",
          "is_clarifying": bool
        }
    """
    combined = f"{history_text} {raw_text}".strip()
    found_symptoms = extract_symptoms(combined)
    red_flags = extract_red_flags(combined)
    severity = extract_severity(combined)
    duration = extract_duration(combined)
    top_matches = score_conditions(found_symptoms)

    # Not enough information yet -> ask a clarifying, form-like question.
    if not red_flags and len(found_symptoms) < 2 and (severity is None):
        return {
            "report_text": build_clarifying_question(found_symptoms),
            "tier": "unknown",
            "is_clarifying": True,
        }

    tier = determine_tier(red_flags, severity, top_matches)

    lines = []
    lines.append(f"**Built-in Diagnostic Engine — Case Assessment**")
    lines.append("")
    lines.append(f"**Triage Level: {TIER_LABELS[tier]}**")
    lines.append("")

    lines.append("**Reported Symptoms**")
    if found_symptoms:
        lines.append(_format_symptom_list(found_symptoms).capitalize() + ".")
    else:
        lines.append("Described in your own words above.")
    if severity is not None:
        lines.append(f"Reported severity: **{severity}/10**.")
    if duration:
        lines.append(f"Reported duration: **{duration}**.")
    lines.append("")

    if red_flags:
        lines.append("**Critical Findings**")
        for rf in red_flags:
            lines.append(f"• {rf.capitalize()}.")
        lines.append("")
        lines.append("**Immediate Action Required**")
        lines.append("Please call your local emergency number or go to the nearest emergency department right now. Do not wait. If possible, have someone stay with you and bring a list of any medications you take.")
        lines.append("")

    elif top_matches:
        lines.append("**Most Likely Conditions**")
        for cond, confidence, matched in top_matches:
            label = "Likely" if confidence >= 55 else "Possible"
            lines.append(f"• **{cond.name}** ({label} match, {confidence}%) — {cond.summary}")
        lines.append("")

        lines.append("**Recommended Guidance**")
        primary = top_matches[0][0]
        for g in primary.guidance:
            lines.append(f"• {g}")
        if tier == "yellow":
            lines.append("• Book an appointment with a physician within the next 24–72 hours for confirmation and treatment.")
        elif tier == "green":
            lines.append("• These steps are usually sufficient, but see a doctor if symptoms worsen or persist beyond a week.")
        lines.append("")

    else:
        lines.append("**Assessment**")
        lines.append("Your description does not closely match a specific condition in this engine's knowledge base. This does not rule out a medical issue.")
        lines.append("")
        lines.append("**Recommended Guidance**")
        lines.append("• Monitor your symptoms closely and note any changes.")
        lines.append("• If symptoms persist beyond 48 hours, worsen, or you feel concerned, consult a physician for an in-person evaluation.")
        lines.append("")

    lines.append("**Important Notice**")
    lines.append(
        "This assessment was generated by the system's built-in rule-based diagnostic engine because the "
        "online AI engine was temporarily unavailable. It is provided for educational and preliminary "
        "guidance purposes only and is not a substitute for professional medical diagnosis, advice, or "
        "treatment. Always consult a qualified physician for any health concern."
    )

    return {
        "report_text": "\n".join(lines),
        "tier": tier,
        "is_clarifying": False,
    }
