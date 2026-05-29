import datetime
import json
import os

STORE_FILE = "ticket_store.json"

def load_store():
    if not os.path.exists(STORE_FILE):
        return {}
    with open(STORE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_store(data):
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def save_ticket_log(ticket_id, ticket_data, thread, intent, summary, reply):

    store = load_store()

    store[str(ticket_id)] = {
        "ticket_id": ticket_id,
        "timestamp": str(datetime.datetime.now()),
        "subject": ticket_data.get("subject"),
        "thread": thread,
        "intent": intent,
        "summary": summary,
        "reply": reply,
        "status": "AUTO_REPLIED"
    }

    save_store(store)       