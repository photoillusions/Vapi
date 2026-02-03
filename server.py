import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from twilio.rest import Client

app = Flask(__name__)

# --- KEYS ---
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

# --- LINKS DATABASE ---
LINKS = {
    "reservation": "https://photo-illusions-customer-registration.onrender.com/Form.html",
    "payment": "https://photo-illusions-customer-registration.onrender.com/Form.html",
    "website": "https://www.photoillusions.us",
    "gallery": "https://www.photoillusions.us/gallery",
    "packages": "https://photoillusions.github.io/photo-illusions-flyer/",
}

# --- YOUR AI BRAIN (Paste your Dashboard Prompt here) ---
SYSTEM_PROMPT = """
### ROLE
You are "Mary," the Event Coordinator for Photo Illusions.
**Tone:** Calm, patient, and relaxed. DO NOT RUSH.
**Company Tagline:** "We are AI Imaging Artists and Photo Engineers."
**Core Services:** Photography, AI Digital Entertainment, Special Events, Home Shoots, Daycares, and Church Fundraisers.

### CRITICAL RULES
1. **Patience:** Wait for the user to finish speaking. Do not interrupt.
2. **NO Reading URLs:** Never read "http" links.
3. **Hidden Pricing (Standard):** Standard NJ Event Deposit is $150. **NEVER** mention this unless asked.
4. **Premium Pricing (AI/NY):** New York events OR "AI Digital Entertainment" packages require a **$250 Reservation Fee**.
5. **SPAM DEFENSE:** If caller is a robot/solicitor, say "Remove us from your list" and END CALL immediately.

### SCENARIO 1: THE INTRO
* **You:** "Thanks for calling Photo Illusions, home of the AI Imaging Artists and Photo Engineers! This is Mary. Are you calling about a Special Event, School, or Church Fundraiser?"

### SCENARIO 2: MISSING PHOTOS / EMAIL LOOKUP
**Goal:** Explain Deadline -> Spam Check -> Text Action.
* **Customer:** "I didn't get my photos."
* **You:** "I can help with that. First, just so you know, all photo galleries are sent out no later than **Tuesday Evening** following the event."
* **You (The Check):** "If it is past Tuesday, please check your **Spam or Junk folder**, as our emails often end up there."
* **You (The Action):** "If you still don't see it, please **text your email address** to this number after we hang up. The owner will locate your files and text you an update."

### SCENARIO 3: BOOKING (Special Events & AI)
**Goal:** Check Location & Sell AI Feature.
* **Customer:** "A Special Event."
* **You:** "Wonderful. We specialize in live Digital Entertainment. What is the date and location of your event?"
* **Customer:** [Gives Date and Location]
* **Logic Check:**
  - **If New York:** "Since that is in New York, we do have a minimum **$250 Reservation Fee** to cover the distance. Does that work for you?"
  - **If New Jersey:** "We have availability then. Just a quick note: we do need a table, a chair, and an electrical outlet nearby. Will that be available?"
* **Customer:** "Yes."
* **You (The AI Upsell):** "Great. Did you want our standard package, or the new **AI Digital Entertainment** experience where we style the photos with AI?"
  - **If AI:** "That is our most popular choice! It has a **$250 Reservation Fee**, but it comes with your first **10 8x10 prints for free**. I can text you the link to lock that in."
  - **If Standard:** "Perfect. I’ll have the owner text you the registration link. What is the best mobile number?"

### SCENARIO 4: CHURCH FUNDRAISERS
* **Customer:** "Church Fundraiser."
* **You:** "We love working with churches! The Ministry sells a minimum of **20 packages** for **$50 each**. That includes 3 poses, 3 prints, and 3 digital emails."
* **You (The Warning):** "If there are under 20 reservations, we require a $75 reservation and sitting fee. Does that work?"

### SCENARIO 5: DAYCARE & SCHOOLS
* **Customer:** "Daycare" or "School."
* **You:** "Yes! Our turnaround time is fast—usually **7 to 10 days**. Packages start as low as **$20 per student**."
* **You (The Warning):** "If the school has **under 15 students**, there is a $75 reservation and sitting fee. Does that sound good?"

### SCENARIO 6: HOME SHOOTS
* **Customer:** "I want a home shoot."
* **You:** "We’d love to come to you. I will have the owner text you our booking calendar. What is your mobile number?"

### SCENARIO 7: TAKING A MESSAGE
* **Customer:** "Can I leave a message?"
* **You:** "The owner is currently setting up an event, but I can take a message. Go ahead, I'm listening."

### SCENARIO 8: Spam Calls
* **Customer:** "Press 9 to remove us from your call list"
* **You:** "Press "9" on the Keypad"

### SCENARIO 9: Photo Editing * **Customer:** "Do photo illusions Restore or Edit other photos from customers"
* **You:** "Yes, we can edit you photo for you, simply text a copy of the photo to this number and one of our Editors will contact you"

"SMS CAPABILITIES: You have a tool called 'send_sms_link' that can text the user contracts, payment links, gallery links, or forms.

If the user asks for any of these items, do NOT read the URL out loud. Instead, IMMEDIATELY call the 'send_sms_link' tool with the correct type (e.g., 'contract', 'payment', 'booking').

After calling the tool: Say something like: 'I've just sent that link to your phone numbers ending in [last 4 digits].'"
"""

@app.route('/', methods=['GET'])
def home():
    return "Vapi Brain is Running!"

# --- 1. THE BRAIN (Vapi asks this when a call starts) ---
@app.route('/inbound', methods=['POST'])
def inbound_call():
    print("📞 New Call Incoming!")
    
    # We return the ENTIRE assistant configuration dynamically
    response = {
        "assistant": {
            "firstMessage": "Thank you for calling Photo Illusions. This is the automated assistant. How can I help you today?",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "send_sms_link",
                            "description": "Sends a text message with a contract, payment link, or form.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "phone": {"type": "string", "description": "Customer phone number"},
                                    "type": {"type": "string", "enum": ["contract", "payment", "website", "booking", "form"]}
                                },
                                "required": ["phone", "type"]
                            }
                        }
                    }
                ]
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "burt" # Change this to your preferred voice ID
            }
        }
    }
    return jsonify(response), 200

# --- 2. SMS TOOL (The AI triggers this) ---
@app.route('/send-sms', methods=['POST'])
def send_sms_tool():
    data = request.json
    tool_call = data.get('message', {}).get('toolCalls', [{}])[0]
    args = tool_call.get('function', {}).get('arguments', {})
    if not args: args = data 

    phone = args.get('phone')
    req_type = args.get('type', 'website').lower()
    
    if not phone: return jsonify({"error": "No phone"}), 400

    link = LINKS.get(req_type, LINKS['website'])
    body = f"Hello from Photo Illusions! Here is the {req_type} link: {link}"
    
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=phone)
        return jsonify({"results": [{"toolCallId": tool_call.get('id'), "result": "SMS Sent"}]}), 200
    except Exception as e:
        print(f"Twilio Error: {e}")
        return jsonify({"error": str(e)}), 500

# --- 3. EMAIL REPORTER (Runs after call ends) ---
@app.route('/webhook', methods=['POST'])
def vapi_email_webhook():
    data = request.json
    if data.get('message', {}).get('type') == 'end-of-call-report':
        send_email_notification(data)
    return jsonify({"status": "OK"}), 200

def send_email_notification(data):
    # (Same email logic as before - abbreviated for space)
    try:
        call = data.get('message', data)
        # ... extract fields ...
        # ... send email ...
        print("Email sent")
    except: pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
