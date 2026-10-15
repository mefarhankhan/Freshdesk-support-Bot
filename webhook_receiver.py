
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
    expected_secret = os.getenv("WEBHOOK_SECRET", "")
    received_secret = request.headers.get("X-Webhook-Secret", "")

    if not expected_secret:
        return jsonify({"error": "Webhook secret is not configured"}), 500

    if not hmac.compare_digest(received_secret, expected_secret):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}

    # Receiver only: do not call the AI bot or send any replies.
    print("Webhook received. Automatic replies are disabled.")

    return jsonify({
        "received": True,
        "auto_reply_enabled": False
    }), 200
