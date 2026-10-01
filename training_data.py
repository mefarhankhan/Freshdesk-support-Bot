import json
import os

TRAINING_FILE = "training_data.json"

def load_training_data():
    if not os.path.exists(TRAINING_FILE):
        return {}
    try:
        with open(TRAINING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_training_data(data):
    with open(TRAINING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def add_training_record(record):
    data = load_training_data()
    key = str(record["ticket_id"])
    data[key] = record
    save_training_data(data)

def get_training_examples(intent, limit=3):
    data = load_training_data()
    matches = [
        r for r in data.values()
        if r.get("intent") == intent and r.get("intent") != "UNKNOWN"
    ]
    matches.sort(key=lambda r: r.get("collected_at", ""), reverse=True)
    return matches[:limit]

def get_unknown_replies():
    data = load_training_data()
    return [
        r for r in data.values()
        if r.get("intent") == "UNKNOWN"
    ]
