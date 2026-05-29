import requests
import json
import re
import os
import time
import datetime

from dotenv import load_dotenv

load_dotenv()

# =========================================
# CONFIG
# =========================================

FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")

DOMAIN = os.getenv("DOMAIN")

MY_AGENT_ID = Your_ID

OLLAMA_URL = "http://localhost:11434/api/generate"

STORE_FILE = "ticket_store.json"

# =========================================
# SOP REPLIES
# =========================================

SOP_REPLIES = {

    "LANGUAGE_ISSUE":
        """Books are delivered in the same language in which the order was placed. Language cannot be changed after order placement.""",

    "ADDRESS_CHANGE":
        """Minor address corrections (house number, landmark, etc.) can be updated. Complete address changes are not allowed. Pincode changes are strictly not permitted.""",

    "INCOMPLETE_SET":
        """Please share clear images of the entire shipment along with the bill/invoice pasted on the shipment for verification.""",

    "ORDER_DELAY":
        """Please wait until the estimated delivery date (EDD). You can also track the latest shipment status here:
https://search-dashboard-uiwb.onrender.com/

If the EDD has already passed and the order is still not delivered/dispatched, kindly report back to us for further investigation.""",

    "ORDER_NOT_FOUND":
        """Please share your registered mobile number/email ID used during purchase or share the order screenshot. Without valid registered details, no action can be taken.""",

    "MISPRINTED_BOOK":
        """Book exchange is not applicable unless it is a major issue. Please share the page numbers and issue details for verification. A PDF of the affected pages/books can be provided after verification.""",

    "TRACK_ORDER":
        """Please use the dashboard to track the status of your books:
https://search-dashboard-uiwb.onrender.com/"""
}


# =========================================
# FETCH MY TICKETS
# =========================================

def fetch_my_tickets():

    url = f"https://{DOMAIN}/api/v2/tickets?filter=new_and_my_open"

    response = requests.get(
        url,
        auth=(FRESHDESK_API_KEY, "X")
    )

    print("\n========== FETCH MY TICKETS RESPONSE ==========\n")
    print(response.status_code)

    if response.status_code != 200:

        print(response.text)

        return []

    data = response.json()

    print(f"\nFOUND {len(data)} TICKETS\n")

    return data

# =========================================
# FETCH SINGLE TICKET
# =========================================

def fetch_ticket(ticket_id):

    url = f"https://{DOMAIN}/api/v2/tickets/{ticket_id}"

    try:

        response = requests.get(
            url,
            auth=(FRESHDESK_API_KEY, "X"),
            timeout=30
        )

        if response.status_code != 200:

            print(f"[ERROR] fetch_ticket failed: {response.status_code}")

            print(response.text)

            return None

        return response.json()

    except Exception as e:

        print(f"[EXCEPTION] fetch_ticket: {e}")

        return None

# =========================================
# FETCH CONVERSATIONS
# =========================================

def fetch_conversations(ticket_id):

    url = f"https://{DOMAIN}/api/v2/tickets/{ticket_id}/conversations"

    try:

        response = requests.get(
            url,
            auth=(FRESHDESK_API_KEY, "X"),
            timeout=30
        )

        if response.status_code != 200:

            print(f"[ERROR] fetch_conversations failed: {response.status_code}")

            print(response.text)

            return []

        return response.json()

    except Exception as e:

        print(f"[EXCEPTION] fetch_conversations: {e}")

        return []

# =========================================
# REMOVE HTML
# =========================================

def strip_html(text):

    if not text:
        return ""

    clean = re.sub(r"<[^>]+>", " ", text)

    clean = re.sub(r"\s+", " ", clean)

    return clean.strip()

# =========================================
# CLEAN TEXT
# =========================================

def clean_text(text):

    if not text:
        return ""

    text = re.sub(
        r"On\s.+?wrote:",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    text = re.sub(
        r"https?:\/\/\S+",
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()

# =========================================
# BUILD THREAD
# =========================================

def build_thread(ticket, conversations):

    thread = ""

    thread += f"""
SUBJECT:
{clean_text(ticket.get("subject", ""))}

"""

    description = (
        ticket.get("description_text")
        or
        strip_html(ticket.get("description", ""))
    )

    thread += f"""
ORIGINAL ISSUE:
{clean_text(description)}

"""

    for convo in conversations:

        if convo.get("private") is True:
            continue

        body = (
            convo.get("body_text")
            or
            strip_html(convo.get("body", ""))
        )

        cleaned = clean_text(body)

        if not cleaned:
            continue

        sender = "CUSTOMER"

        if convo.get("incoming") is False:
            sender = "AGENT"

        thread += f"""
{sender}:
{cleaned}

"""

    return thread

# =========================================
# CHECK IF ALREADY PROCESSED
# =========================================

def already_processed(conversations):

    for convo in conversations:

        body = (
            convo.get("body_text")
            or
            strip_html(convo.get("body", ""))
        )

        body_lower = body.lower()

        user_id = convo.get("user_id")

        incoming = convo.get("incoming")

        # =====================================
        # BOT ALREADY REPLIED
        # =====================================

        if "[fbot_reply]" in body_lower:

            print("BOT ALREADY REPLIED")

            return True

        # =====================================
        # YOU ALREADY REPLIED
        # =====================================

        if (
            incoming is False
            and user_id == MY_AGENT_ID
        ):

            print("YOU ALREADY REPLIED")

            return True

    return False
# =========================================
# EXTRACT JSON
# =========================================

def extract_json(text):

    print("\n========== RAW TEXT FOR JSON EXTRACTION ==========\n")
    print(text)

    valid_intents = [

        "LANGUAGE_ISSUE",
        "ADDRESS_CHANGE",
        "INCOMPLETE_SET",
        "ORDER_DELAY",
        "ORDER_NOT_FOUND",
        "MISPRINTED_BOOK",
        "TRACK_ORDER",
        "UNKNOWN"
    ]

    match = re.search(
        r"\{[\s\S]*?\}",
        text
    )

    if match:

        try:

            parsed = json.loads(match.group())

            return {
                "intent": parsed.get("intent", "UNKNOWN"),
                "summary": parsed.get("summary", "")
            }

        except:
            pass

    upper_text = text.upper()

    for intent in valid_intents:

        if intent in upper_text:

            return {
                "intent": intent,
                "summary": text
            }

    lower = text.lower()

    # MISPRINT SAFE DETECTION

    if (
        "misprint" in lower
        or "misprinted" in lower
        or "pages not printed" in lower
        or "blank page" in lower
        or "damaged pages" in lower
        or "printing mistake" in lower
    ):

        return {
            "intent": "MISPRINTED_BOOK",
            "summary": "Customer reports misprinted and damaged book."
        }

    return {
        "intent": "UNKNOWN",
        "summary": text
    }

# =========================================
# VALIDATE INTENT
# =========================================

def validate_intent(intent, thread):

    print("\n========== VALIDATING INTENT ==========\n")
    print(f"AI INTENT: {intent}")

    text = thread.lower()

    # =====================================
    # FORCE INCOMPLETE SET
    # =====================================

    wrong_delivery_patterns = [

        "wrong book delivered",
        "wrong books delivered",
        "wrong product received",
        "incorrect product",
        "received wrong item",
        "different language received",
        "hindi instead of english",
        "english instead of hindi",
        "wrong language received",
        "received wrong language",
        "language mismatch"
    ]

    for pattern in wrong_delivery_patterns:

        if pattern in text:

            print("\nFORCED => INCOMPLETE_SET\n")

            return "INCOMPLETE_SET"

    # =====================================
    # MISPRINTED BOOK PRIORITY
    # =====================================

    misprint_words = [

        "misprint",
        "misprinted",
        "printing mistake",
        "blank page",
        "blurred",
        "duplicate page",
        "unreadable",
        "pages not printed",
        "damaged pages",
        "missing print",
        "torn pages"
    ]

    for word in misprint_words:

        if word in text:

            return "MISPRINTED_BOOK"

    # =====================================
    # LANGUAGE ISSUE
    # =====================================

    if intent == "LANGUAGE_ISSUE":

        valid_words = [

            "change language",
            "want english",
            "want hindi",
            "need english",
            "need hindi",
            "convert language",
            "replace language",
            "change medium"
        ]

        for word in valid_words:

            if word in text:

                return "LANGUAGE_ISSUE"

        return "UNKNOWN"

    # =====================================
    # ADDRESS CHANGE
    # =====================================

    if intent == "ADDRESS_CHANGE":

        blocked_words = [

            "batch",
            "course",
            "migration",
            "faculty",
            "subscription",
            "english medium",
            "hinglish",
            "class",
            "academic"
        ]

        for word in blocked_words:

            if word in text:

                return "UNKNOWN"

        valid_words = [

            "address",
            "house number",
            "landmark",
            "street",
            "pincode",
            "delivery address",
            "location"
        ]

        for word in valid_words:

            if word in text:

                return "ADDRESS_CHANGE"

        return "UNKNOWN"

    # =====================================
    # INCOMPLETE SET
    # =====================================

    if intent == "INCOMPLETE_SET":

        return "INCOMPLETE_SET"

    # =====================================
    # ORDER DELAY
    # =====================================

    if intent == "ORDER_DELAY":

        valid_words = [

            "delayed",
            "late delivery",
            "delivery delayed",
            "not delivered",
            "not dispatched",
            "dispatch pending",
            "expected dispatch",
            "delivery timeline",
            "order not shipped",
            "dispatch status"
        ]

        for word in valid_words:

            if word in text:

                return "ORDER_DELAY"

        return "UNKNOWN"

    # =====================================
    # ORDER NOT FOUND
    # =====================================

    if intent == "ORDER_NOT_FOUND":

        valid_words = [

            "payment successful",
            "order not visible",
            "order not showing",
            "unable to trace",
            "cannot find order",
            "order missing"
        ]

        for word in valid_words:

            if word in text:

                return "ORDER_NOT_FOUND"

        return "UNKNOWN"

    # =====================================
    # TRACK ORDER
    # =====================================

    if intent == "TRACK_ORDER":

        valid_words = [

            "track order",
            "tracking link",
            "track shipment",
            "shipment tracking",
            "delivery status",
            "where is my order"
        ]

        for word in valid_words:

            if word in text:

                return "TRACK_ORDER"

        return "UNKNOWN"

    return "UNKNOWN"

# =========================================
# AI ANALYZER
# =========================================

def analyze_ticket(thread):

    prompt = f"""

You are an expert customer support AI.

Analyze the ENTIRE support ticket carefully.

IMPORTANT:
- Understand the REAL customer issue
- Ignore greetings/signatures
- Ignore repeated followups
- Ignore automated replies
- Ignore agent reminders

Return STRICT JSON ONLY.

FORMAT:

{{
    "intent": "",
    "summary": ""
}}

VALID INTENTS:
- LANGUAGE_ISSUE
- ADDRESS_CHANGE
- INCOMPLETE_SET
- ORDER_DELAY
- ORDER_NOT_FOUND
- MISPRINTED_BOOK
- TRACK_ORDER
- UNKNOWN

TICKET:

{thread}

"""

    payload = {
        "model": "llama3",
        "prompt": prompt,
        "stream": False
    }

    try:

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=40
        )

        data = response.json()

        raw = data.get("response", "")

        print("\n========== RAW AI RESPONSE ==========\n")
        print(raw)

        return extract_json(raw)

    except Exception as e:

        print(f"\nOLLAMA ERROR: {e}\n")

        return {
            "intent": "UNKNOWN",
            "summary": "AI timeout/error"
        }
# =========================================
# SAVE TICKET LOG
# =========================================

def save_ticket_log(ticket_id, ticket_data, thread, intent, summary, reply):

    if os.path.exists(STORE_FILE):

        with open(STORE_FILE, "r", encoding="utf-8") as f:

            store = json.load(f)

    else:

        store = {}

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

    with open(STORE_FILE, "w", encoding="utf-8") as f:

        json.dump(
            store,
            f,
            indent=2,
            ensure_ascii=False
        )

# =========================================
# ADD PRIVATE NOTE
# =========================================

def add_private_note(ticket_id, note, conversations):

    previous_agent_id = None

    for convo in reversed(conversations):

        incoming = convo.get("incoming")

        user_id = convo.get("user_id")

        if (
            incoming is False
            and user_id
            and user_id != MY_AGENT_ID
        ):

            previous_agent_id = user_id

            break

    note_url = f"https://{DOMAIN}/api/v2/tickets/{ticket_id}/notes"

    payload = {

        "body": f"""
<b>[FBOT_REPLY]</b>
<br><br>
{note}
""",

        "private": True
    }

    print("\n========== NOTE PAYLOAD ==========\n")
    print(json.dumps(payload, indent=2))

    response = requests.post(
        note_url,
        auth=(FRESHDESK_API_KEY, "X"),
        json=payload,
        timeout=30
    )

    print("\n========== NOTE RESPONSE ==========\n")
    print(response.status_code)
    print(response.text)

    # =====================================
    # REASSIGN BACK
    # =====================================

    if previous_agent_id:

        assign_url = (
            f"https://{DOMAIN}/api/v2/tickets/{ticket_id}"
        )

        assign_payload = {
            "responder_id": previous_agent_id
        }

        assign_response = requests.put(
            assign_url,
            auth=(FRESHDESK_API_KEY, "X"),
            json=assign_payload,
            timeout=30
        )

        print("\n========== REASSIGN RESPONSE ==========\n")
        print(assign_response.status_code)

# =========================================
# PROCESS TICKET
# =========================================

def process_ticket(ticket_id):

    print(f"\nCHECKING TICKET: {ticket_id}\n")

    ticket = fetch_ticket(ticket_id)

    if not ticket:
        return

    conversations = fetch_conversations(ticket_id)

    if already_processed(conversations):

        print("\nSKIPPING TICKET\n")

        return

    thread = build_thread(
        ticket,
        conversations
    )

    ai_result = analyze_ticket(thread)

    print("\n========== AI RESULT ==========\n")
    print(ai_result)

    intent = ai_result.get(
        "intent",
        "UNKNOWN"
    )

    intent = validate_intent(
        intent,
        thread
    )

    summary = ai_result.get(
        "summary",
        ""
    )

    print("\n========== DETECTED INTENT ==========\n")
    print(intent)

    print("\n========== SUMMARY ==========\n")
    print(summary)

    if intent == "UNKNOWN":

        print("\nNO SAFE SOP FOUND\n")

        return

    final_reply = SOP_REPLIES.get(intent)

    if not final_reply:

        print("\nNO SOP FOUND\n")

        return

    print("\n========== FINAL REPLY ==========\n")
    print(final_reply)

    add_private_note(
        ticket_id,
        final_reply,
        conversations
    )

    save_ticket_log(
        ticket_id,
        ticket,
        thread,
        intent,
        summary,
        final_reply
    )

    print("\n========== BOT REPLY ADDED ==========\n")


# =========================================
# MAIN
# =========================================

def main():

    print("\n========== PRODUCTION MODE STARTED ==========\n")

    try:

        tickets = fetch_my_tickets()

        print(f"\nFOUND {len(tickets)} TICKETS\n")

        if not tickets:

            print("NO TICKETS FOUND")

            return

        # =====================================
        # LOOP TICKETS
        # =====================================

        for ticket in tickets:

            try:

                responder_id = ticket.get("responder_id")

                ticket_id = ticket.get("id")

                status = ticket.get("status")

                subject = ticket.get("subject", "")

                print("\n===================================")
                print(f"CHECKING TICKET: {ticket_id}")
                print(f"SUBJECT: {subject}")
                print(f"RESPONDER ID: {responder_id}")
                print(f"STATUS: {status}")
                print("===================================\n")

                # =================================
                # ONLY MY TICKETS
                # =================================

                if responder_id != MY_AGENT_ID:

                    print("SKIPPED => NOT ASSIGNED TO ME\n")

                    continue

                # =================================
                # SKIP RESOLVED/CLOSED
                # =================================

                # 4 = Resolved
                # 5 = Closed

                if status in [4, 5]:

                    print("SKIPPED => CLOSED/RESOLVED\n")

                    continue

                # =================================
                # PROCESS TICKET
                # =================================

                process_ticket(ticket_id)

                # =================================
                # SMALL DELAY
                # =================================

                time.sleep(2)

            except Exception as e:

                print(f"\nERROR IN TICKET {ticket.get('id')}: {e}\n")

                continue

    except Exception as e:

        print(f"\nMAIN ERROR: {e}\n")


# =========================================

main()
