import requests
import json
import re
import os
import sys
import time
import datetime

from dotenv import load_dotenv
from training_data import (
    load_training_data,
    add_training_record,
    get_unknown_replies,
)

load_dotenv()

# =========================================
# CONFIG
# =========================================

FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")

DOMAIN = os.getenv("DOMAIN")

MY_AGENT_ID = 31027813716

OLLAMA_URL = "http://localhost:11434/api/generate"

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))

MAX_AI_THREAD_CHARS = int(os.getenv("MAX_AI_THREAD_CHARS", "6000"))

TICKET_FETCH_SCOPE = os.getenv("TICKET_FETCH_SCOPE", "assigned").lower()

FRESHDESK_STATUS_IDS = os.getenv(
    "FRESHDESK_STATUS_IDS",
    "2,3,6,7,8"
)

STORE_FILE = "ticket_store.json"


def normalize_id(value):

    try:

        return int(value)

    except (TypeError, ValueError):

        return None


def get_freshdesk_status_ids():

    status_ids = []

    for value in FRESHDESK_STATUS_IDS.split(","):

        status_id = normalize_id(value.strip())

        if status_id:

            status_ids.append(status_id)

    return status_ids


def requires_manual_handling(thread):

    text = thread.lower()

    manual_patterns = [

        "batch medium change",
        "batch medium",
        "medium change",
        "change the batch",
        "change batch",
        "current batch",
        "requested batch",
        "batch:",
        "batch -",
        "course change",
        "change course",
        "subscription",
        "migration",
        "faculty",
        "academic",
        "hinglish"
    ]

    # "batch" alone causes false positives (e.g. "batch student" in address tickets)
    # only block bare "batch" if it appears with course/medium context
    batch_context_words = [
        "course", "medium", "change", "migrate", "migration",
        "faculty", "subject", "class", "enroll", "enrollment"
    ]
    if "batch" in text and any(w in text for w in batch_context_words):
        print("\nMANUAL HANDLING REQUIRED => batch (with context)\n")
        return True

    for pattern in manual_patterns:

        if pattern in text:

            print(f"\nMANUAL HANDLING REQUIRED => {pattern}\n")

            return True

    return False


def prepare_ai_thread(thread):

    if len(thread) <= MAX_AI_THREAD_CHARS:

        return thread

    return thread[:MAX_AI_THREAD_CHARS]

# =========================================
# SOP REPLIES
# =========================================

SOP_REPLIES = {

    "LANGUAGE_ISSUE":
        """Books are delivered in the same language in which the order was placed. Language cannot be changed after order placement.""",

    "ADDRESS_CHANGE":
        """Minor address corrections (house number, landmark, etc.) can be updated. Complete address changes are not allowed. Pincode changes are strictly not permitted.""",

    "INCOMPLETE_SET":
        """Please ask user to share clear images of the entire shipment along with the bill/invoice pasted on the shipment for verification.""",

    "ORDER_DELAY":
        """Please wait until the estimated delivery date (EDD). You can also track the latest shipment status here:
https://search-dashboard-uiwb.onrender.com/

If the EDD has already passed and the order is still not delivered/dispatched, kindly report back to us for further investigation.""",

    "ORDER_NOT_FOUND":
        """Kindly check user with the given details on the Dashboard https://search-dashboard-uiwb.onrender.com/ If not found Please ask user to  share the registered mobile number/email ID used during purchase or share the order screenshot. Without valid registered details, no action can be taken.""",

    "MISPRINTED_BOOK":
        """Book exchange is not applicable unless it is a major issue. Please share the page numbers and issue details for verification. A PDF of the affected pages/books can be provided after verification.""",

    "TRACK_ORDER":
        """Please use the dashboard to track the status of your books:
https://search-dashboard-uiwb.onrender.com/""",

    "EBOOK_ISSUE":
        """Please note that E-Books are digital products — no physical delivery will be made for E-Book orders.
    Your E-Book should have been sent to your registered email address after successful payment.
 If User have not received it on his registered email, please write back to us and we will assist you further."""
}


# =========================================
# FETCH MY TICKETS
# =========================================


def fetch_my_tickets():

    page = 1

    all_tickets = []

    status_ids = get_freshdesk_status_ids()

    status_query = " OR ".join(
        f"status:{status_id}"
        for status_id in status_ids
    )

    while True:

        unresolved_query = f"({status_query})"

        if TICKET_FETCH_SCOPE == "all":

            query = unresolved_query

        else:

            query = (
                f"agent_id:{MY_AGENT_ID} "
                f"AND {unresolved_query}"
            )

        url = (
            f"https://{DOMAIN}/api/v2/search/tickets"
        )

        response = requests.get(
            url,
            auth=(FRESHDESK_API_KEY, "X"),
            params={
                "query": f"\"{query}\"",
                "page": page
            },
            timeout=30
        )

        print("\n========== SEARCH RESPONSE ==========\n")
        print(response.status_code)
        print(f"FETCH SCOPE => {TICKET_FETCH_SCOPE}")
        print(f"QUERY => {query}")

        if response.status_code != 200:
            print(response.text)
            break

        data = response.json()

        results = data.get("results", [])

        print(
            f"PAGE {page} => FOUND {len(results)} TICKETS"
        )

        if not results:
            break

        all_tickets.extend(results)

        if len(results) < 30:
            break

        page += 1

    print(
        f"\nTOTAL TICKETS FOUND => {len(all_tickets)}\n"
    )

    return all_tickets

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
        "EBOOK_ISSUE",
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
                "summary": parsed.get("summary", ""),
                "evidence": parsed.get("evidence", "")
            }

        except:
            pass

    upper_text = text.upper()

    for intent in valid_intents:

        if intent in upper_text:

            return {
                "intent": intent,
                "summary": text,
                "evidence": ""
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
            "summary": "Customer reports misprinted and damaged book.",
            "evidence": ""
        }

    return {
        "intent": "UNKNOWN",
        "summary": text,
        "evidence": ""
    }

# =========================================
# FORCED OVERRIDE PATTERNS
# (shared by validate_intent and ground_intent -
# these always win regardless of AI/keyword intent)
# =========================================

WRONG_DELIVERY_PATTERNS = [

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

MISPRINT_WORDS = [

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

# =========================================
# VALIDATE INTENT
# (keyword-only classifier - kept for classify_ticket_without_ai,
# which has no AI evidence to ground against)
# =========================================

def validate_intent(intent, thread):

    print("\n========== VALIDATING INTENT ==========\n")
    print(f"AI INTENT: {intent}")

    text = thread.lower()

    if requires_manual_handling(thread):

        return "UNKNOWN"

    # =====================================
    # FORCE INCOMPLETE SET
    # =====================================

    for pattern in WRONG_DELIVERY_PATTERNS:

        if pattern in text:

            print("\nFORCED => INCOMPLETE_SET\n")

            return "INCOMPLETE_SET"

    # =====================================
    # MISPRINTED BOOK PRIORITY
    # =====================================

    for word in MISPRINT_WORDS:

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

        valid_words = [

            "address",
            "house number",
            "landmark",
            "street",
            "pincode",
            "delivery address",
            "location"
        ]

        has_valid_word = any(word in text for word in valid_words)

        blocked_words = [

            "change batch",
            "change my batch",
            "batch change",
            "shift batch",
            "change course",
            "change my course",
            "course change",
            "course migration",
            "migrate batch",
            "migrate course",
            "change faculty",
            "faculty change",
            "change subscription",
            "subscription change",
            "change medium",
            "medium change",
            "english medium",
            "hinglish medium",
            "change class",
            "class change",
            "academic year change"
        ]

        has_blocked_word = any(word in text for word in blocked_words)

        if has_blocked_word and not has_valid_word:

            return "UNKNOWN"

        if has_valid_word:

            return "ADDRESS_CHANGE"

        return "UNKNOWN"

    # =====================================
    # INCOMPLETE SET
    # =====================================

    if intent == "INCOMPLETE_SET":

        valid_words = [

            "wrong book delivered",
            "wrong books delivered",
            "wrong product received",
            "incorrect product",
            "received wrong item",
            "different language received",
            "wrong language received",
            "received wrong language",
            "language mismatch",
            "incomplete set",
            "missing book",
            "book missing",
            "product missing",
            "item missing",
            "inside the box is missing",
            "received only",
            "less quantity",
            "partial delivery"
        ]

        for word in valid_words:

            if word in text:

                return "INCOMPLETE_SET"

        return "UNKNOWN"

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
            "dispatch status",
            "not received the book",
            "not received book",
            "not receive the book",
            "not receive book",
            "not received",
            "not receive",
            "haven't received",
            "havent received",
            "not recieved",
            "books not recieved",
            "books not received",
            "book not received",
            "not received my order",
            "not receive my order",
            "didnt receive my order",
            "didn't receive my order",
            "still not received",
            "till now books not received",
            "books get delivered",
            "get delivered",
            "expected shipping date",
            "shipping date",
            "delivery status",
            "shipment process",
            "when will i get my order",
            "when will i get",
            "when can i get",
            "when can i receive",
            "when will the book",
            "when is the book",
            "when coming",
            "when will it come",
            "when will i receive",
            "delivery date",
            "when will book",
            "not yet received",
            "not yet delivered",
            "haven't yet received",
            "havent yet received",
            "yet to receive",
            "yet to be delivered",
            "delay"
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
            "order missing",
            "order not found",
            "order is not shown",
            "order is not visible",
            "didn't get confirmation",
            "didnt get confirmation",
            "no confirmation",
            "order not confirmed",
            "payment done",
            "payment is done",
            "payment was done",
            "transactions pending",
            "transaction pending",
            "payment pending",
            "payment made",
            "made payment",
            "i made payment",
            "order not received confirmation",
            "no order found",
            "have not ordered",
            "i have not ordered",
            "shows i have not",
            "not ordered anything",
            "i have also paid",
            "i have paid",
            "already paid",
            "paid for",
            "haven't got any confirmation",
            "not got any confirmation",
            "neither i have got",
            "not received any confirmation",
            "not showing in my account",
            "not visible in my account",
            "not showing in account",
            "not in my account",
            "not reflecting",
            "order not reflecting"
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
            "track my order",
            "track the order",
            "tracking link",
            "track shipment",
            "shipment tracking",
            "delivery status",
            "where is my order",
            "tracking number",
            "tracking id",
            "traking",
            "contact number",
            "current status of my book",
            "status of my book",
            "Status of my order",
            "despatch",
            "details of despatch",
        ]

        for word in valid_words:

            if word in text:

                return "TRACK_ORDER"

        return "UNKNOWN"

    # =====================================
    # EBOOK ISSUE
    # =====================================

    if intent == "EBOOK_ISSUE":

        valid_words = [

            "ebook",
            "E book",
            "e-book",
            "e book",
            "digital book",
            "pdf of ebook",
            "ebook not received",
            "ebook not found",
            "ebook not delivered",
            "ebook not sent",

    
        ]

        for word in valid_words:

            if word in text:

                return "EBOOK_ISSUE"

        return "UNKNOWN"

    return "UNKNOWN"

# =========================================
# EVIDENCE GROUNDING
# (used for live tickets - trusts the AI's own
# intent as long as it points to something real)
# =========================================

def normalize_text(s):

    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_evidence_grounded(evidence, thread):

    norm_evidence = normalize_text(evidence)

    if not norm_evidence:

        return False

    norm_thread = normalize_text(thread)

    if norm_evidence in norm_thread:

        return True

    # fuzzy fallback: local model may reword slightly when "quoting"
    evidence_words = norm_evidence.split()

    if len(evidence_words) < 3:

        return False

    matches = sum(1 for w in evidence_words if w in norm_thread)

    return (matches / len(evidence_words)) >= 0.8


def ground_intent(ai_intent, evidence, thread):

    print("\n========== GROUNDING INTENT ==========\n")
    print(f"AI INTENT: {ai_intent}")
    print(f"EVIDENCE: {evidence}")

    text = thread.lower()

    if requires_manual_handling(thread):

        return "UNKNOWN"

    # Forced overrides always win, regardless of what the AI said
    for pattern in WRONG_DELIVERY_PATTERNS:

        if pattern in text:

            print("\nFORCED => INCOMPLETE_SET\n")

            return "INCOMPLETE_SET"

    for word in MISPRINT_WORDS:

        if word in text:

            print("\nFORCED => MISPRINTED_BOOK\n")

            return "MISPRINTED_BOOK"

    if ai_intent == "UNKNOWN":

        return "UNKNOWN"

    # LANGUAGE_ISSUE is only for changing the language of an order already
    # placed/delivered. Grounded evidence alone can't tell an availability
    # question ("is this available in Bengali?") apart from an actual
    # change request - both quote real text - so this needs its own guard.
    if ai_intent == "LANGUAGE_ISSUE":

        availability_patterns = [

            "is this book available",
            "is this available",
            "is it available in",
            "available in",
            "be released",
            "released in the future",
            "future edition",
            "any plans to release",
            "planning to release",
            "will there be a",
            "do you provide this in",
            "do you have this in"
        ]

        if any(p in text for p in availability_patterns):

            print("\nFORCED => UNKNOWN (availability question, not a change request)\n")

            return "UNKNOWN"

    if not (evidence or "").strip():

        # AI gave no evidence to check at all (model inconsistency,
        # not a hallucination) - fall back to keyword confirmation
        # instead of discarding a possibly-correct intent.
        print("\nNO EVIDENCE PROVIDED => FALLING BACK TO KEYWORD CHECK\n")

        return validate_intent(ai_intent, thread)

    if is_evidence_grounded(evidence, thread):

        return ai_intent

    print("\nUNGROUNDED EVIDENCE => FORCING UNKNOWN\n")

    return "UNKNOWN"

# =========================================
# FALLBACK ANALYZER
# =========================================

def classify_ticket_without_ai(thread, summary):

    fallback_intents = [

        "MISPRINTED_BOOK",
        "INCOMPLETE_SET",
        "ORDER_NOT_FOUND",
        "ORDER_DELAY",
        "TRACK_ORDER",
        "ADDRESS_CHANGE",
        "LANGUAGE_ISSUE",
        "EBOOK_ISSUE"
    ]

    for intent in fallback_intents:

        validated_intent = validate_intent(
            intent,
            thread
        )

        if validated_intent != "UNKNOWN":

            print("\n========== FALLBACK INTENT ==========\n")
            print(validated_intent)

            return {
                "intent": validated_intent,
                "summary": summary
            }

    return {
        "intent": "UNKNOWN",
        "summary": summary
    }

# =========================================
# TRAINING HELPERS
# =========================================

def get_training_examples_for_prompt(thread):
    if len(thread) > 4000:
        return ""
    data = load_training_data()
    records = [r for r in data.values() if r.get("intent") and r.get("intent") != "UNKNOWN"]
    if not records:
        return ""
    thread_words = set(re.findall(r'\w+', thread.lower()))
    def score(r):
        words = set(re.findall(r'\w+', r.get("thread", "").lower()))
        return len(thread_words & words)
    records.sort(key=score, reverse=True)
    top = records[:3]
    lines = ["EXAMPLES OF PAST TICKETS AND THEIR CORRECT CLASSIFICATION:\n"]
    total = 0
    for i, r in enumerate(top, 1):
        snippet = r.get("thread", "")[:400]
        block = f"Example {i}:\nTICKET CONTEXT:\n{snippet}\nCORRECT INTENT: {r['intent']}\n"
        if total + len(block) > 1200:
            break
        lines.append(block)
        total += len(block)
    return "\n".join(lines) if len(lines) > 1 else ""


def get_learned_sop(thread):
    unknown_records = get_unknown_replies()
    if len(unknown_records) < 3:
        return None
    unknown_records.sort(key=lambda r: r.get("collected_at", ""), reverse=True)
    reply = unknown_records[0].get("your_reply", "").strip()
    if not reply:
        return None
    return "[LEARNED REPLY - based on your past manual replies]\n\n" + reply


# =========================================
# AI ANALYZER
# =========================================

def analyze_ticket(thread):

    ai_thread = prepare_ai_thread(thread)

    few_shot_block = get_training_examples_for_prompt(thread)

    prompt = f"""

You are an expert customer support AI.

Analyze the ENTIRE support ticket carefully.

IMPORTANT:
- Understand the REAL customer issue
- Ignore greetings/signatures
- Ignore repeated followups
- Ignore automated replies
- Ignore agent reminders
- Classify only from the customer's actual issue, not from one keyword.
- If the ticket is about a batch, course, subscription, class, faculty, academic medium, Hinglish/Hindi batch change, or course migration, return UNKNOWN.
- "evidence" must be a short phrase or sentence copied WORD-FOR-WORD from the customer's own message in the ticket that justifies your chosen intent. Do not paraphrase it. If intent is UNKNOWN, leave evidence empty.

Return STRICT JSON ONLY.
Do not write explanations before or after the JSON.

FORMAT:

{{
    "intent": "",
    "summary": "",
    "evidence": ""
}}

VALID INTENTS:
- LANGUAGE_ISSUE
- ADDRESS_CHANGE
- INCOMPLETE_SET
- ORDER_DELAY
- ORDER_NOT_FOUND
- MISPRINTED_BOOK
- TRACK_ORDER
- EBOOK_ISSUE
- UNKNOWN

INTENT RULES:

LANGUAGE_ISSUE:
Use only when the customer wants to change the language of a book they have already ordered/delivered.
Do not use for batch/course/class medium changes.
Do not use for questions about whether a book is available in another language, or requests/suggestions for a future edition in another language - those are UNKNOWN.

ADDRESS_CHANGE:
Use only for minor delivery address correction requests.

INCOMPLETE_SET:
Use only when the customer received a shipment but some item/book is missing, wrong, incomplete, or a wrong language book was delivered.
Do not use for course/batch/academic medium changes.

ORDER_DELAY:
Use when books/order/study material has not been received, delivery is delayed, dispatch is pending, shipment is pending, tracking is unavailable, or the customer asks when the order will arrive.

ORDER_NOT_FOUND:
Use only when payment was successful but the order is not visible/found in Testbook records/app/account.
Do not use for delivery delay after an order exists.

MISPRINTED_BOOK:
Use only when the received book has printing defects, blank pages, torn pages, blurred pages, duplicate pages, or unreadable print.

TRACK_ORDER:
Use when the customer only asks for the tracking link/status and does not report a delay or non-delivery.

EBOOK_ISSUE:
Use when the customer has purchased an E-Book (digital/PDF/soft copy) and is asking about delivery, access, download link, or has not received it on their email. Do not use for physical book orders.

UNKNOWN:
Use when the issue is outside these SOPs, unclear, or needs manual handling.

{few_shot_block}

TICKET:

{ai_thread}

"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": "10m",
        "options": {
            "temperature": 0,
            "num_predict": 120,
            "num_ctx": 2048
        }
    }

    try:

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=(10, OLLAMA_TIMEOUT)
        )

        response.raise_for_status()

        data = response.json()

        raw = data.get("response", "")

        print("\n========== RAW AI RESPONSE ==========\n")
        print(raw)

        return extract_json(raw)

    except Exception as e:

        print(f"\nOLLAMA ERROR: {e}\n")

        return {
            "intent": "UNKNOWN",
            "summary": f"AI timeout/error: {e}",
            "evidence": ""
        }
# =========================================
# SAVE TICKET LOG
# =========================================

def save_ticket_log(ticket_id, ticket_data, thread, intent, summary, reply):

    try:

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

        print(
            f"\nSAVED TICKET {ticket_id} TO {os.path.abspath(STORE_FILE)}\n"
        )

    except Exception as e:

        print(f"\nSTORE ERROR FOR TICKET {ticket_id}: {e}\n")

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

    try:

        response = requests.post(
            note_url,
            auth=(FRESHDESK_API_KEY, "X"),
            json=payload,
            timeout=30
        )

    except requests.exceptions.RequestException as e:

        print(f"\nNOTE REQUEST FAILED (connection error): {e}\n")

        return False

    print("\n========== NOTE RESPONSE ==========\n")
    print(response.status_code)
    print(response.text)

    if response.status_code not in [200, 201]:

        print("\nNOTE FAILED => TICKET NOT STORED AS AUTO_REPLIED\n")

        return False

    # =====================================
    # REASSIGN BACK
    # =====================================
    # Note is already posted at this point - a failure here is
    # secondary and must not discard the reply that already went out.

    if previous_agent_id:

        assign_url = (
            f"https://{DOMAIN}/api/v2/tickets/{ticket_id}"
        )

        assign_payload = {
            "responder_id": previous_agent_id
        }

        try:

            assign_response = requests.put(
                assign_url,
                auth=(FRESHDESK_API_KEY, "X"),
                json=assign_payload,
                timeout=30
            )

            print("\n========== REASSIGN RESPONSE ==========\n")
            print(assign_response.status_code)

        except requests.exceptions.RequestException as e:

            print(f"\nREASSIGN FAILED (connection error, note already posted): {e}\n")

    return True


# =========================================
# CHECK IF MOBILE/EMAIL ALREADY PROVIDED
# =========================================

def has_registered_details(thread):

    mobile_pattern = r'\b[6-9]\d{9}\b'

    email_pattern = (
        r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}'
    )

    mobile_found = re.search(
        mobile_pattern,
        thread,
        re.IGNORECASE
    )

    email_found = re.search(
        email_pattern,
        thread,
        re.IGNORECASE
    )

    return bool(mobile_found or email_found)

# =========================================
# CHECK MISPRINT DETAILS PROVIDED
# =========================================

def has_misprint_details(thread):

    page_keywords = [
        "page",
        "page no",
        "page number",
        "pages",
        "image attached",
        "attached image",
        "attached file",
        "pdf attached",
        "screenshot"
    ]

    text = thread.lower()

    for word in page_keywords:

        if word in text:
            return True

    return False

# =========================================
# SMART SOP OVERRIDE
# =========================================

def get_dynamic_reply(intent, thread):

    # -------------------------------------
    # ORDER NOT FOUND
    # -------------------------------------

    if intent == "ORDER_NOT_FOUND":

        if has_registered_details(thread):

            return """
Please use the dashboard below to check your order status:

https://search-dashboard-uiwb.onrender.com/

If the order is still not visible there, kindly report back to us for further investigation.
"""

    # -------------------------------------
    # MISPRINTED BOOK
    # -------------------------------------

    if intent == "MISPRINTED_BOOK":

        if not has_misprint_details(thread):

            return """
Book exchange is not applicable unless it is a major issue.

Please share:
- A images of affected pages OR
- Exact page numbers where the issue exists

After verification, a PDF replacement of affected pages/book can be provided.
"""

    return SOP_REPLIES.get(intent)        

# =========================================
# PROCESS TICKET
# =========================================

def process_ticket(ticket_id):

    print(f"\nCHECKING TICKET: {ticket_id}\n")

    ticket = fetch_ticket(ticket_id)

    if not ticket:
        return "skipped"

    responder_id = normalize_id(
        ticket.get("responder_id")
        or ticket.get("agent_id")
    )

    if responder_id != MY_AGENT_ID:

        print("\nSKIPPING TICKET => NOT ASSIGNED TO ME\n")

        return "skipped"

    conversations = fetch_conversations(ticket_id)

    if already_processed(conversations):

        print("\nSKIPPING TICKET\n")

        return "skipped"

    thread = build_thread(
        ticket,
        conversations
    )

    print("\n========== CLEAN THREAD ==========\n")
    print(thread)

    if requires_manual_handling(thread):

        print("\nNO BOT REPLY => MANUAL HANDLING REQUIRED\n")

        return "manual"

    # =====================================
    # ANALYZE
    # =====================================

    ai_result = analyze_ticket(thread)

    print("\n========== AI RESULT ==========\n")
    print(ai_result)

    ai_intent = ai_result.get(
        "intent",
        "UNKNOWN"
    )

    ai_evidence = ai_result.get(
        "evidence",
        ""
    )

    # =====================================
    # VALIDATE (evidence-grounded)
    # =====================================

    intent = ground_intent(
        ai_intent,
        ai_evidence,
        thread
    )

    # =====================================
    # SAFE FALLBACK
    # AI thinks this is about order delivery, but the text is too vague
    # to confirm an actual delay (e.g. "please deliver my book").
    # Fall back to the generic tracking SOP instead of skipping the ticket.
    # =====================================

    if intent == "UNKNOWN" and ai_intent == "ORDER_DELAY":

        print("\nFALLBACK => ORDER_DELAY UNCONFIRMED, USING TRACK_ORDER SOP\n")

        intent = "TRACK_ORDER"

    summary = ai_result.get(
        "summary",
        ""
    )

    print("\n========== DETECTED INTENT ==========\n")
    print(intent)

    print("\n========== SUMMARY ==========\n")
    print(summary)

    # =====================================
    # UNKNOWN
    # =====================================

    if intent == "UNKNOWN":

        learned = get_learned_sop(thread)

        if learned:

            print("\nUSING LEARNED SOP FROM YOUR PAST REPLIES\n")

            final_reply = learned

        else:

            print("\nNO SAFE SOP FOUND\n")

            return "no_sop"

    # =====================================
    # DYNAMIC SOP SELECTION
    # =====================================

    if intent != "UNKNOWN":

        final_reply = get_dynamic_reply(
            intent,
            thread
        )

        if not final_reply:

            print("\nNO SOP FOUND\n")

            return "no_sop"

    print("\n========== FINAL REPLY ==========\n")
    print(final_reply)

    # =====================================
    # ADD NOTE
    # =====================================

    note_added = add_private_note(
        ticket_id,
        final_reply,
        conversations
    )

    if not note_added:

        print("\nSKIPPING STORE => NOTE WAS NOT ADDED\n")

        return "error"

    # =====================================
    # SAVE LOG
    # =====================================

    save_ticket_log(
        ticket_id,
        ticket,
        thread,
        intent,
        summary,
        final_reply
    )

    print("\n========== BOT REPLY ADDED ==========\n")

    return "processed"
# =========================================
# COLLECT TRAINING DATA
# =========================================

def collect_training_data():

    print("\n========== COLLECT TRAINING DATA ==========\n")

    existing = load_training_data()

    tickets = fetch_my_tickets()

    print(f"FOUND {len(tickets)} TICKETS\n")

    collected = 0
    skipped_existing = 0
    skipped_no_reply = 0

    for ticket in tickets:

        ticket_id = ticket.get("id")

        if str(ticket_id) in existing:
            skipped_existing += 1
            continue

        conversations = fetch_conversations(ticket_id)

        # Find most recent manual reply: outgoing from MY_AGENT_ID, no [fbot_reply] tag
        your_reply_text = None

        for convo in reversed(conversations):

            if (
                convo.get("incoming") is False
                and normalize_id(convo.get("user_id")) == MY_AGENT_ID
                and "[fbot_reply]" not in (convo.get("body_text") or "").lower()
                and "[fbot_reply]" not in (convo.get("body") or "").lower()
            ):

                your_reply_text = (convo.get("body_text") or "").strip()
                break

        if not your_reply_text:
            skipped_no_reply += 1
            continue

        thread = build_thread(ticket, conversations)

        ai_result = classify_ticket_without_ai(thread, "")

        intent = ai_result.get("intent", "UNKNOWN")

        intent_source = "keyword_match" if intent != "UNKNOWN" else "unresolved"

        record = {
            "ticket_id": ticket_id,
            "collected_at": str(datetime.datetime.now()),
            "subject": ticket.get("subject", ""),
            "thread": thread,
            "your_reply": your_reply_text,
            "intent": intent,
            "intent_source": intent_source,
        }

        add_training_record(record)

        print(f"COLLECTED TICKET {ticket_id} => INTENT: {intent}")

        collected += 1

    print(f"\n========== COLLECTION SUMMARY ==========")
    print(f"COLLECTED: {collected}")
    print(f"SKIPPED (already collected): {skipped_existing}")
    print(f"SKIPPED (no manual reply found): {skipped_no_reply}")
    print(f"TRAINING FILE: training_data.json\n")


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

        stats = {
            "checked": 0,
            "processed": 0,
            "skipped_not_assigned": 0,
            "skipped_closed": 0,
            "skipped_already_replied": 0,
            "skipped_manual": 0,
            "skipped_no_sop": 0,
            "errors": 0
        }

        for ticket in tickets:

            try:

                stats["checked"] += 1

                responder_id = normalize_id(
                      ticket.get("responder_id")
                    or ticket.get("agent_id")
                    )

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

                    stats["skipped_not_assigned"] += 1

                    print("SKIPPED => NOT ASSIGNED TO ME\n")

                    continue

                # =================================
                # SKIP RESOLVED/CLOSED
                # =================================

                # 4 = Resolved
                # 5 = Closed

                if status in [4, 5]:

                    stats["skipped_closed"] += 1

                    print("SKIPPED => CLOSED/RESOLVED\n")

                    continue

                # =================================
                # PROCESS TICKET
                # =================================

                result = process_ticket(ticket_id)

                if result == "processed":
                    stats["processed"] += 1
                elif result == "skipped":
                    stats["skipped_already_replied"] += 1
                elif result == "manual":
                    stats["skipped_manual"] += 1
                elif result == "no_sop":
                    stats["skipped_no_sop"] += 1
                elif result == "error":
                    stats["errors"] += 1

                # =================================
                # SMALL DELAY
                # =================================

                time.sleep(2)

            except Exception as e:

                stats["errors"] += 1

                print(f"\nERROR IN TICKET {ticket.get('id')}: {e}\n")

                continue

        print("\n========== RUN SUMMARY ==========\n")
        print(f"CHECKED: {stats['checked']}")
        print(f"PROCESSED: {stats['processed']}")
        print(f"SKIPPED NOT ASSIGNED: {stats['skipped_not_assigned']}")
        print(f"SKIPPED CLOSED/RESOLVED: {stats['skipped_closed']}")
        print(f"SKIPPED ALREADY REPLIED: {stats['skipped_already_replied']}")
        print(f"SKIPPED MANUAL HANDLING: {stats['skipped_manual']}")
        print(f"SKIPPED NO SOP: {stats['skipped_no_sop']}")
        print(f"ERRORS: {stats['errors']}")

    except Exception as e:

        print(f"\nMAIN ERROR: {e}\n")


# =========================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--collect":
        collect_training_data()
    else:
        main()
