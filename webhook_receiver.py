
import os
import hmac
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

@app.get("/")
def health():
    return jsonify({
        "status": "online",
        "service": "Freshdesk AI Bot Webhook",
        "auto_reply_enabled": False
    }), 200

@app.post("/freshdesk-webhook")
def freshdesk_webhook():
    expected = os.getenv("WEBHOOK_SECRET", "")
    received = request.headers.get("X-Webhook-Secret", "")

    if not expected:
        return jsonify({"error": "Webhook secret not configured"}), 500

    if not hmac.compare_digest(received, expected):
        return jsonify({"error": "Unauthorized"}), 401

    # Receiver only: no ticket processing or replies.
    print("Webhook received. Automatic replies are disabled.")

    return jsonify({
        "received": True,
        "auto_reply_enabled": False
    }), 200
