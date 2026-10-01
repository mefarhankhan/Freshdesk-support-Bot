import requests
import os
from dotenv import load_dotenv

# =========================================
# LOAD ENV
# =========================================

load_dotenv()

FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")
DOMAIN = os.getenv("DOMAIN")

BOT_AGENT_ID = 31027813716  # Replace with your bot/automation agent ID

# =========================================
# ADD NOTE + REASSIGN
# =========================================

def add_note_and_reassign(ticket_id, note_text):
    try:
        print(f"\nProcessing Ticket: {ticket_id}")

        # ---------------------------------
        # Get Current Ticket
        # ---------------------------------

        ticket_url = f"https://{DOMAIN}/api/v2/tickets/{ticket_id}"

        ticket_response = requests.get(
            ticket_url,
            auth=(FRESHDESK_API_KEY, "X"),
            timeout=30
        )

        if ticket_response.status_code != 200:
            print("❌ Failed to fetch ticket")
            print(ticket_response.text)
            return

        # ---------------------------------
        # Add Private Note
        # ---------------------------------

        note_url = f"https://{DOMAIN}/api/v2/tickets/{ticket_id}/notes"

        payload = {
            "body": note_text,
            "private": True
        }

        note_response = requests.post(
            note_url,
            auth=(FRESHDESK_API_KEY, "X"),
            json=payload,
            timeout=30
        )

        if note_response.status_code not in [200, 201]:
            print("❌ Failed to add note")
            print(note_response.text)
            return

        print("✅ Private note added")

        # ---------------------------------
        # Get Conversations
        # ---------------------------------

        conv_url = f"https://{DOMAIN}/api/v2/tickets/{ticket_id}/conversations"

        conv_response = requests.get(
            conv_url,
            auth=(FRESHDESK_API_KEY, "X"),
            timeout=30
        )

        if conv_response.status_code != 200:
            print("❌ Failed to fetch conversations")
            print(conv_response.text)
            return

        conversations = conv_response.json()

        previous_agent_id = None

        # Find the last agent who replied before the bot
        for convo in reversed(conversations):

            if (
                convo.get("incoming") is False
                and convo.get("user_id")
                and convo.get("user_id") != BOT_AGENT_ID
            ):
                previous_agent_id = convo.get("user_id")
                break

        if not previous_agent_id:
            print("⚠️ No previous agent found")
            return

        # ---------------------------------
        # Reassign Ticket
        # ---------------------------------

        assign_url = f"https://{DOMAIN}/api/v2/tickets/{ticket_id}"

        assign_payload = {
            "responder_id": previous_agent_id
        }

        assign_response = requests.put(
            assign_url,
            auth=(FRESHDESK_API_KEY, "X"),
            json=assign_payload,
            timeout=30
        )

        if assign_response.status_code == 200:
            print(
                f"✅ Ticket {ticket_id} reassigned to agent {previous_agent_id}"
            )
        else:
            print("❌ Failed to reassign ticket")
            print(assign_response.text)

    except Exception as e:
        print(f"❌ Error processing ticket {ticket_id}: {e}")


# =========================================
# MAIN
# =========================================

if __name__ == "__main__":

    ticket_input = input(
        "\nEnter Ticket IDs (comma separated):\n"
    )

    ticket_ids = [
        int(x.strip())
        for x in ticket_input.split(",")
        if x.strip()
    ]

    print("\nEnter Private Note:")
    note_text = input("> ")

    print(f"\nFound {len(ticket_ids)} tickets")

    for ticket_id in ticket_ids:
        add_note_and_reassign(ticket_id, note_text)

    print("\nDone!")