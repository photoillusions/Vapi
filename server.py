import json
import os
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# --- CONFIGURATION ---
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")  # Your business number in E.164 e.g. +15551234567
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
OWNER_PHONE_NUMBER = os.environ.get("OWNER_PHONE_NUMBER", "+16099978843")
VAPI_PRIVATE_KEY = os.environ.get("VAPI_PRIVATE_KEY", "")

CRM_STORE_PATH = os.path.join(os.path.dirname(__file__), "crm_store.json")

SERVICE_LINKS = {
    "website": "photoillusions.us",
    "booking": "photoillusions.us/book",
    "payment": "photoillusions.us/pay",
    "contract": "photoillusions.us/contract",
    "portfolio": "photoillusions.us/gallery",
}



SYSTEM_PROMPT = """
# Mary — Photo Illusions AI Phone Assistant
**Core Directive:** Route fast, be warm, never trap a caller in questions. A live person is always one sentence away.
You are Mary, an AI assistant for Photo Illusions — an AI portrait photography company. You are NOT a human.

## ABSOLUTE RULES (do not break these)
1. **ONE question per turn. Maximum.** Never list "1, 2, 3..." questions.
2. **Maximum 25 words per reply.** Long replies cause callers to hang up.
3. **Never ask more than one question before offering a transfer.**
4. **Never say "I don't know"** — say "Let me get the right person for that."
5. **Never claim a tool is "disabled" or "unavailable."** If a tool fails, say "Let me have someone follow up" and call request_callback.
6. **Never spell an email back to the caller.** If you mishear an email twice, stop trying — call request_callback and let a human confirm by text.
7. **Never say "AI-generated" unprompted.** Say "created with cutting-edge AI technology."
8. **Never confirm a booking** without reading back the date and name.
9. You are an AI. If asked, say so plainly. Never claim to be human.
10. You already have the caller's phone from caller ID. NEVER ask for it.
11. Never read card numbers back aloud.

## FIRST 10 SECONDS — Categorize the call
Listen to the caller's first sentence and pick ONE bucket. When signals overlap, use this **priority order**:
**C > D > A > F > D2 > G > H > B > E > Z**
(Frustrated or photo-related = always escalate first.)

### 🔴 Bucket A — "Speak to a person"
Triggers: person, human, live, representative, agent, someone, somebody, real person, "talk to you", "speak with you".
→ Say: "Of course — connecting you now."
→ Immediately call **transferCall** on the FIRST turn. Caller ID is enough. Zero questions.

### 🟡 Bucket B — Callback request
Triggers: "call me back", "have someone call me", "reach out to me", "tell [name] to call me".
→ Call **request_callback** with whatever you have.
→ Say: "Done — someone will call you back shortly."
→ Call **endCall**.

### 🟠 Bucket C — Frustrated / repeat caller
Triggers: "no one called me back", "I called before", "this is ridiculous", "stop", "just—", upset tone.
→ Say: "I'm so sorry — I'm flagging this as urgent right now."
→ Call **request_callback** with urgency="high".
→ Call **endCall**. No more questions.

### 🟣 Bucket D — Photo delivery (past event)
Triggers: "where are my pictures", "I paid for photos", "never got my photos", "my order", any past-event reference, pickup.
→ You CANNOT retrieve photos. Do not ask for email/venue/date/event details — NOT EVEN ONE follow-up question.
→ On the FIRST turn, call **request_callback** with message="Customer needs photos from past event — please pull order and call back" and urgency="high".
→ Say: "I'm flagging this for our team — they'll pull up your order and call you right back."
→ Call **endCall**.

### 🟫 Bucket D2 — Reprints / additional prints
Triggers: "reprint", "more copies", "order more", "can I buy more", "another set".
→ Say: "Absolutely — I'm connecting you with our team to handle that."
→ Call **transferCall**. If it fails, call **request_callback** with message="Caller wants reprints / additional prints" and say: "They'll call you back about your reprint order."
→ Then call **endCall**.

### 🟢 Bucket E — Booking / pricing / services
Triggers: wants to book, asks pricing, asks what you offer, "do you do weddings/events/graduations".
→ ONLY bucket with questions. Enter Booking Flow below.

### 🔵 Bucket F — Asks for staff member by name
Triggers: names Anthony, Tony, George, Sarah, or any staff member.
→ Say: "Sure — let me try to connect you."
→ Immediately call **transferCall**. If it fails, call **request_callback** with message="Caller asked for [name]" and **endCall**.
→ NEVER ask "what is this regarding" or "may I have your email" before transferring.

### 📧 Bucket G — Missing email
Triggers: "didn't get", "never received", "missing", "resend", "check spam".
→ If under 3 business days: "Please allow up to 3 business days — also check your spam and promotions folders."
→ If over 3 business days OR frustrated: "Please text your email address to this same number you called, and our team will resend it right away."
→ Call **request_callback** with message="Customer reports missing email — asked them to text their address for resend" (urgency="high" if frustrated, else "normal").
→ Call **endCall**. Do NOT try to capture or spell their email on this call.

### 🟦 Bucket H — AI / portfolio curiosity
Triggers: "is this AI", "are these real photos", "can I see examples", "what does it look like", "do you use AI", "show me your work", "portfolio".
→ Say: "Great question — Photo Illusions uses cutting-edge AI to create stunning, professional portraits live at your event. Every image is generated in real time and printed on-site. You can see examples at photoillusions.us — want me to text you that link right now?"
→ If yes: call **send_sms_link** with type="portfolio" → confirm sent → call **endCall**.
→ If no: call **endCall**.

### ⬜ Bucket Z — Wrong number / confused
Triggers: "who is this", "I think I have the wrong number", extreme confusion, no clear purpose.
→ Say: "No worries — you've reached Photo Illusions, an AI portrait photography company in New Jersey. Anything I can help you with?"
→ If still confused or says wrong number: "No problem, have a great day!" → call **endCall**.

**Default when unsure:** Bucket A (transfer). Never trap a caller in questions.

## Booking Flow (Bucket E only)
One question at a time. Wait for the answer before the next.

1. "What type of event is this?" (listen for: birthday, graduation, wedding, corporate, fraternal/organization, school, other)
2. "What date are you looking at?"
   → If they say "tonight", "today", or "tomorrow" → say "That's urgent — let me get our team on the line right now" → call **transferCall** immediately. If transfer fails, call **request_callback** with urgency="high".
3. "Roughly how many guests are you expecting?"
4. "And what's the best name for the booking?"
5. "What's the best email to send your confirmation to?"
   → Capture once. Do NOT spell it back. If you mishear it twice, stop — say "No worries, I'll have a team member text you to confirm the email" → call **request_callback** with message="Confirm email for booking" and continue with the booking using whatever you captured.
6. "Last thing — what city or venue are you thinking?"

→ Silently call **check_availability** with the date.
→ If available: call **book_appointment** → read back date + name to confirm → call **send_booking_email** → "You're booked. Anything else?" → **endCall** when done.
→ If unavailable: "That date isn't open yet — can I check one nearby?" → offer ONE alternative → if no match, call **request_callback** → "Our team will reach out with available dates." → **endCall**.

Do NOT ask about deposit, props, backdrop, add-ons unless the caller asks first.
If you mishear an email twice during booking, stop — call **request_callback** and continue with the booking using your best guess; a human will confirm by text.

## After-Hours Awareness
Business hours: **9 AM – 7 PM Eastern, Monday – Saturday.**
If the call comes in OUTSIDE those hours:
→ Say: "Thanks for calling Photo Illusions! Our team isn't available right now, but I can make sure someone gets back to you. Can I get the name for the callback?"
→ Capture name (one question only) → call **request_callback** → "Got it — they'll reach out first thing." → **endCall**.
→ NEVER say "we're closed." Always say "our team isn't available right now."
→ Bucket A (live transfer) is still allowed after-hours — the call may roll to voicemail, that's fine.

## Ending the call
- When caller says "thanks," "bye," "okay good," "alright," "have a good one" — say "Thanks for calling Photo Illusions, have a great day!" and call **endCall** immediately.
- After any transfer, callback, or completed booking — call **endCall**.

## Returning customers
When you have CRM context, briefly acknowledge prior service. Example: "Welcome back — great to hear from you again."
For returning customers, call **lookup_customer** once you have their name to confirm details.
"""


def mask(value):
    if not value:
        return "MISSING"
    if len(value) < 8:
        return "SET"
    return f"{value[:4]}...{value[-4:]}"


def load_crm():
    if not os.path.exists(CRM_STORE_PATH):
        return {}
    try:
        with open(CRM_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_crm(data):
    with open(CRM_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def normalize_phone(phone):
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return str(phone)


def get_caller_phone(payload):
    try:
        phone = payload.get("message", {}).get("call", {}).get("customer", {}).get("number")
        if phone:
            return normalize_phone(phone)
    except Exception:
        pass
    try:
        phone = payload.get("message", {}).get("customer", {}).get("number")
        if phone:
            return normalize_phone(phone)
    except Exception:
        pass
    return ""


def extract_tool_call(data):
    tool_call_id = None
    function_name = None
    args = {}
    try:
        tool_calls = data.get("message", {}).get("toolCalls", []) or data.get("message", {}).get("toolCallList", [])
        if tool_calls:
            call = tool_calls[0]
            tool_call_id = call.get("id")
            function = call.get("function", {})
            function_name = function.get("name") or call.get("name")
            args = function.get("arguments", {}) if function else call.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
    except Exception:
        pass
    return tool_call_id, function_name, args or {}


def tool_result(tool_call_id, result):
    return jsonify({"results": [{"toolCallId": tool_call_id, "result": result}]})


def get_base_url(req):
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    proto = req.headers.get("X-Forwarded-Proto", req.scheme)
    host = req.headers.get("X-Forwarded-Host", req.host)
    return f"{proto}://{host}".rstrip("/")


def get_calendar_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except Exception:
        return None

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    try:
        sa_info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/calendar"]
        )
        return build("calendar", "v3", credentials=creds)
    except Exception:
        return None


def send_email(to_email, subject, body):
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not to_email:
        return False
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()
    return True


@app.route("/", methods=["GET"])
def home():
    return "Photo Illusions Vapi Server v2.0 — Online"


@app.route("/debug", methods=["GET"])
def debug():
    return jsonify(
        {
            "email_sender": mask(EMAIL_SENDER),
            "email_receiver": mask(EMAIL_RECEIVER),
            "twilio_sid": mask(TWILIO_ACCOUNT_SID),
            "twilio_phone": TWILIO_PHONE_NUMBER or "MISSING",
            "stripe_key": mask(STRIPE_SECRET_KEY),
            "calendar_id": GOOGLE_CALENDAR_ID,
            "service_account": "SET" if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") else "MISSING",
            "public_base_url": PUBLIC_BASE_URL or "(dynamic)",
        }
    )


@app.route("/inbound", methods=["POST"])
def inbound_call():
    data = request.json or {}
    message_type = data.get("message", {}).get("type")

    if message_type == "end-of-call-report":
        try:
            call = data.get("message", data)
            summary = call.get("summary", "No summary.")
            transcript = call.get("transcript", "No transcript.")
            if EMAIL_RECEIVER:
                send_email(EMAIL_RECEIVER, "Photo Illusions Call Report", f"Summary:\n{summary}\n\nTranscript:\n{transcript}")
        except Exception:
            pass
        return jsonify({"status": "ok"}), 200

    if message_type != "assistant-request":
        return jsonify({"status": "acknowledged"}), 200

    base = get_base_url(request)
    caller_phone = get_caller_phone(data)

    prompt = SYSTEM_PROMPT
    if caller_phone:
        prompt += f"\n\n## Caller Info\n- Phone: {caller_phone}\n- You already have this from caller ID."
        crm = load_crm()
        existing = crm.get(caller_phone)
        if existing:
            prompt += (
                "\n\n## Returning Customer Context\n"
                f"- Name: {existing.get('name', 'Unknown')}\n"
                f"- Email: {existing.get('email', 'Unknown')}\n"
                f"- Last service: {existing.get('service_type', 'Unknown')}\n"
                f"- Last date: {existing.get('event_date', 'Unknown')}\n"
                f"- Notes: {existing.get('notes', '')}"
            )

    response = {
        "assistant": {
            "firstMessage": "Hi, this is Mary at Photo Illusions — how can I help?",
            "firstMessageMode": "assistant-speaks-first",
            "voicemailDetectionEnabled": True,
            "endCallMessage": "Thanks for calling Photo Illusions. Have a great day!",
            "endCallPhrases": ["goodbye", "bye", "have a good day", "have a great day", "talk to you later"],
            "model": {
                "provider": "openai",
                "model": "gpt-5-mini",
                "messages": [{"role": "system", "content": prompt}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "send_text_intro",
                            "description": "Send the caller an intro SMS with the business texting number. Call this at the start of every call.",
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "required": [],
                            },
                        },
                        "server": {"url": f"{base}/send-text-intro"},
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_customer",
                            "description": "Look up returning customer details using caller ID phone.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "customer_name": {"type": "string"}
                                },
                                "required": ["customer_name"],
                            },
                        },
                        "server": {"url": f"{base}/lookup-customer-tool"},
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "check_availability",
                            "description": "Check calendar availability for requested start/end time.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "start_time": {"type": "string", "description": "ISO 8601"},
                                    "end_time": {"type": "string", "description": "ISO 8601"},
                                },
                                "required": ["start_time", "end_time"],
                            },
                        },
                        "server": {"url": f"{base}/calendar-tool"},
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "book_appointment",
                            "description": "Book or pencil in a photography appointment.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "summary": {"type": "string"},
                                    "start_time": {"type": "string"},
                                    "end_time": {"type": "string"},
                                    "attendee_email": {"type": "string"},
                                    "customer_name": {"type": "string"},
                                    "service_type": {"type": "string"},
                                    "location": {"type": "string"},
                                    "description": {"type": "string"},
                                    "price_quote": {"type": "string"},
                                },
                                "required": ["summary", "start_time", "end_time", "customer_name"],
                            },
                        },
                        "server": {"url": f"{base}/calendar-tool"},
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "process_payment",
                            "description": "Process card payment for booking deposit.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "amount": {"type": "string"},
                                    "card_number": {"type": "string"},
                                    "exp_month": {"type": "string"},
                                    "exp_year": {"type": "string"},
                                    "cvc": {"type": "string"},
                                    "zip": {"type": "string"},
                                    "customer_name": {"type": "string"},
                                    "customer_email": {"type": "string"},
                                    "service_type": {"type": "string"},
                                    "event_date": {"type": "string"},
                                },
                                "required": [
                                    "amount",
                                    "card_number",
                                    "exp_month",
                                    "exp_year",
                                    "cvc",
                                    "zip",
                                    "customer_name",
                                    "customer_email",
                                ],
                            },
                        },
                        "server": {"url": f"{base}/payment-tool"},
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "send_booking_email",
                            "description": "Send booking/payment confirmation email to customer and office.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "customer_name": {"type": "string"},
                                    "customer_email": {"type": "string"},
                                    "service_type": {"type": "string"},
                                    "event_date": {"type": "string"},
                                    "event_time": {"type": "string"},
                                    "location": {"type": "string"},
                                    "deposit_paid": {"type": "string"},
                                    "confirmation_number": {"type": "string"},
                                },
                                "required": ["customer_name", "customer_email", "service_type", "deposit_paid"],
                            },
                        },
                        "server": {"url": f"{base}/booking-email-tool"},
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "send_info_email",
                            "description": "Send package/service info email.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "customer_name": {"type": "string"},
                                    "customer_email": {"type": "string"},
                                    "service_type": {"type": "string"},
                                    "notes": {"type": "string"},
                                },
                                "required": ["customer_name", "customer_email"],
                            },
                        },
                        "server": {"url": f"{base}/info-email-tool"},
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "send_sms_link",
                            "description": "Send customer a booking/payment/website link via SMS.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "phone": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": ["contract", "payment", "website", "booking", "portfolio"],
                                    },
                                },
                                "required": ["type"],
                            },
                        },
                        "server": {"url": f"{base}/send-sms"},
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "request_callback",
                            "description": "Log a callback request and notify the Photo Illusions team via email. Use this whenever a caller wants someone to call them back, wants to leave a message, or is a repeat caller who was missed.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "caller_name": {"type": "string", "description": "Caller's name if provided"},
                                    "message": {"type": "string", "description": "The message or request details"},
                                    "requested_staff": {"type": "string", "description": "Specific staff member requested (e.g. Tony, Debbie, Kirk)"},
                                    "urgency": {"type": "string", "enum": ["normal", "high"], "description": "Set to high if caller is frustrated or says they called before with no response"},
                                },
                                "required": ["message"],
                            },
                        },
                        "server": {"url": f"{base}/request-callback"},
                    },
                    {
                        # Vapi NATIVE transfer tool — actually warm-transfers the call
                        # to the owner's phone instead of just sending an email.
                        "type": "transferCall",
                        "destinations": [
                            {
                                "type": "number",
                                "number": OWNER_PHONE_NUMBER,
                                "message": "Connecting you now to our team. One moment please.",
                                "transferPlan": {"mode": "blind-transfer"},
                            }
                        ],
                    },
                    {
                        # Vapi NATIVE end-call tool — lets Mary hang up cleanly
                        # when the caller says "thanks, bye" instead of waiting
                        # for the silence timeout (the #1 failure pattern).
                        "type": "endCall",
                    },
                ],
            },
            "serverMessages": ["end-of-call-report"],
            "silenceTimeoutSeconds": 12,
            "maxDurationSeconds": 600,
            "backgroundDenoisingEnabled": True,
            "startSpeakingPlan": {
                "waitSeconds": 0.4,
                "smartEndpointingEnabled": True,
            },
            "stopSpeakingPlan": {
                "numWords": 2,
                "voiceSeconds": 0.2,
                "backoffSeconds": 1.0,
            },
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "en-US",
                "endpointing": 300,
                "smartFormat": True,
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "EXAVITQu4vr4xnSDxMaL",
                "stability": 0.5,
                "similarityBoost": 0.75,
                "speed": 1.0,
            },
        }
    }
    return jsonify(response), 200


@app.route("/send-text-intro", methods=["POST"])
def send_text_intro():
    data = request.json or {}
    tool_call_id, _, args = extract_tool_call(data)
    phone = normalize_phone(get_caller_phone(data))

    if not phone:
        return tool_result(tool_call_id, "No phone number available from caller ID."), 200
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
        return tool_result(tool_call_id, "SMS system not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER."), 200

    message_body = (
        f"Hey! Thanks for calling Photo Illusions 📸\n\n"
        f"You can text THIS number anytime for:\n"
        f"✅ Booking & scheduling\n"
        f"✅ Pricing & packages\n"
        f"✅ Questions or concerns\n"
        f"✅ Photo delivery status\n\n"
        f"Just reply to this text anytime!\n\n"
        f"We reply fast! 💬\n"
        f"— Photo Illusions Team\n"
        f"photoillusions.us"
    )

    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=phone,
        )
        if msg.sid:
            return tool_result(tool_call_id, "Intro text sent successfully from your business number."), 200
        return tool_result(tool_call_id, "SMS send returned no confirmation."), 200
    except Exception as e:
        return tool_result(tool_call_id, f"SMS error: {str(e)}"), 200


@app.route("/lookup-customer-tool", methods=["POST"])
def lookup_customer_tool():
    data = request.json or {}
    tool_call_id, _, args = extract_tool_call(data)
    phone = get_caller_phone(data)
    crm = load_crm()
    customer = crm.get(phone)
    if not customer:
        return tool_result(tool_call_id, f"NEW CUSTOMER — Phone: {phone or 'unknown'}"), 200
    result = (
        f"RETURNING CUSTOMER — Name: {customer.get('name', 'Unknown')} | "
        f"Email: {customer.get('email', 'Unknown')} | "
        f"Service: {customer.get('service_type', 'Unknown')} | "
        f"Date: {customer.get('event_date', 'Unknown')} | "
        f"Notes: {customer.get('notes', '')}"
    )
    return tool_result(tool_call_id, result), 200


@app.route("/calendar-tool", methods=["POST"])
def calendar_tool():
    data = request.json or {}
    tool_call_id, function_name, args = extract_tool_call(data)

    calendar_service = get_calendar_service()
    if function_name == "check_availability":
        start_iso = args.get("start_time")
        end_iso = args.get("end_time")
        if not start_iso or not end_iso:
            return tool_result(tool_call_id, "Missing start_time or end_time."), 200

        if not calendar_service:
            return tool_result(tool_call_id, "Calendar not configured. Please set GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_CALENDAR_ID."), 200

        try:
            freebusy = calendar_service.freebusy().query(
                body={
                    "timeMin": start_iso,
                    "timeMax": end_iso,
                    "items": [{"id": GOOGLE_CALENDAR_ID}],
                }
            ).execute()
            busy = freebusy.get("calendars", {}).get(GOOGLE_CALENDAR_ID, {}).get("busy", [])
            if busy:
                return tool_result(tool_call_id, "That time is not available. Please offer another slot."), 200
            return tool_result(tool_call_id, "Available."), 200
        except Exception as e:
            return tool_result(tool_call_id, f"Calendar error: {str(e)}"), 200

    if function_name == "book_appointment":
        if not calendar_service:
            return tool_result(tool_call_id, "Calendar not configured. Please set GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_CALENDAR_ID."), 200

        try:
            summary = args.get("summary", "Photo Illusions Booking")
            start_iso = args.get("start_time")
            end_iso = args.get("end_time")
            event = {
                "summary": summary,
                "location": args.get("location", "Photo Illusions"),
                "description": args.get("description", ""),
                "start": {"dateTime": start_iso, "timeZone": "America/New_York"},
                "end": {"dateTime": end_iso, "timeZone": "America/New_York"},
            }
            created = calendar_service.events().insert(
                calendarId=GOOGLE_CALENDAR_ID,
                body=event,
                sendUpdates="none",
            ).execute()

            phone = get_caller_phone(data)
            crm = load_crm()
            if phone:
                crm[phone] = {
                    "name": args.get("customer_name", ""),
                    "email": args.get("attendee_email", ""),
                    "service_type": args.get("service_type", ""),
                    "event_date": (start_iso or "")[:10],
                    "notes": args.get("description", ""),
                    "updated_at": datetime.utcnow().isoformat(),
                }
                save_crm(crm)

            return tool_result(tool_call_id, f"Booked successfully. Event ID: {created.get('id', 'N/A')}."), 200
        except Exception as e:
            return tool_result(tool_call_id, f"Booking error: {str(e)}"), 200

    return tool_result(tool_call_id, "Unknown calendar function."), 200


@app.route("/payment-tool", methods=["POST"])
def payment_tool():
    data = request.json or {}
    tool_call_id, _, args = extract_tool_call(data)

    if not STRIPE_SECRET_KEY:
        return tool_result(tool_call_id, "Payment system not configured. Add STRIPE_SECRET_KEY."), 200

    try:
        import stripe
    except Exception:
        return tool_result(tool_call_id, "Stripe library not installed on server."), 200

    try:
        stripe.api_key = STRIPE_SECRET_KEY
        amount_cents = int(float(args.get("amount", "0")) * 100)
        if amount_cents <= 0:
            return tool_result(tool_call_id, "Invalid amount."), 200

        pm = stripe.PaymentMethod.create(
            type="card",
            card={
                "number": str(args.get("card_number", "")).replace(" ", "").replace("-", ""),
                "exp_month": int(args.get("exp_month", "1")),
                "exp_year": int(f"20{args.get('exp_year')}" if len(str(args.get("exp_year", ""))) == 2 else args.get("exp_year", "2026")),
                "cvc": str(args.get("cvc", "")),
            },
            billing_details={
                "name": args.get("customer_name", ""),
                "email": args.get("customer_email", ""),
                "address": {"postal_code": args.get("zip", "")},
            },
        )

        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            payment_method=pm.id,
            confirm=True,
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            description=f"Photo Illusions booking deposit - {args.get('customer_name', '')}",
            receipt_email=args.get("customer_email", ""),
            metadata={
                "service_type": args.get("service_type", ""),
                "event_date": args.get("event_date", ""),
            },
        )

        if intent.status == "succeeded":
            conf = f"PILL-{intent.id[-8:].upper()}"
            phone = get_caller_phone(data)
            crm = load_crm()
            if phone:
                existing = crm.get(phone, {})
                existing.update(
                    {
                        "name": args.get("customer_name", existing.get("name", "")),
                        "email": args.get("customer_email", existing.get("email", "")),
                        "last_payment_amount": args.get("amount"),
                        "last_payment_date": datetime.utcnow().strftime("%Y-%m-%d"),
                        "confirmation_number": conf,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                )
                crm[phone] = existing
                save_crm(crm)
            return tool_result(tool_call_id, f"Payment succeeded. Confirmation number: {conf}"), 200

        return tool_result(tool_call_id, f"Payment status: {intent.status}"), 200
    except Exception as e:
        return tool_result(tool_call_id, f"Payment error: {str(e)}"), 200


@app.route("/booking-email-tool", methods=["POST"])
def booking_email_tool():
    data = request.json or {}
    tool_call_id, _, args = extract_tool_call(data)

    customer_name = args.get("customer_name", "Customer")
    customer_email = args.get("customer_email", "")
    service_type = args.get("service_type", "Session")
    event_date = args.get("event_date", "TBD")
    event_time = args.get("event_time", "TBD")
    location = args.get("location", "Photo Illusions")
    deposit = args.get("deposit_paid", "0")
    confirmation = args.get("confirmation_number", "Pending")

    body = f"""Booking Confirmation — Photo Illusions

Client: {customer_name}
Service: {service_type}
Date: {event_date}
Time: {event_time}
Location: {location}
Deposit Paid: ${deposit}
Confirmation: {confirmation}

Thank you for booking with Photo Illusions.
Website: photoillusions.us
Email: photoillusions@photoillusions.us
"""

    try:
        sent_customer = send_email(customer_email, "Photo Illusions Booking Confirmation", body)
        sent_mgmt = send_email(EMAIL_RECEIVER, f"New Booking: {customer_name}", body) if EMAIL_RECEIVER else False
        if sent_customer:
            return tool_result(tool_call_id, "Confirmation email sent successfully."), 200
        return tool_result(tool_call_id, "Email not sent: check EMAIL_SENDER/EMAIL_PASSWORD config."), 200
    except Exception as e:
        return tool_result(tool_call_id, f"Email error: {str(e)}"), 200


@app.route("/info-email-tool", methods=["POST"])
def info_email_tool():
    data = request.json or {}
    tool_call_id, _, args = extract_tool_call(data)

    customer_name = args.get("customer_name", "there")
    customer_email = args.get("customer_email", "")
    service_type = args.get("service_type", "Photo/Video Services")
    notes = args.get("notes", "")

    body = f"""Hi {customer_name},

Thanks for contacting Photo Illusions.

Service interest: {service_type}

What we offer:
- Portrait sessions
- Event coverage
- Video add-ons
- Fast turnaround + premium edits

To lock your date, a deposit payment is required.

Useful links:
- Booking: {SERVICE_LINKS['booking']}
- Payment: {SERVICE_LINKS['payment']}
- Portfolio: {SERVICE_LINKS['portfolio']}

Notes from your call:
{notes}

Best,
Photo Illusions
photoillusions@photoillusions.us
"""

    try:
        sent = send_email(customer_email, "Photo Illusions Service Info", body)
        if EMAIL_RECEIVER:
            send_email(EMAIL_RECEIVER, f"New Lead: {customer_name}", body)
        if sent:
            return tool_result(tool_call_id, f"Service info emailed to {customer_email}."), 200
        return tool_result(tool_call_id, "Email not sent: check EMAIL_SENDER/EMAIL_PASSWORD config."), 200
    except Exception as e:
        return tool_result(tool_call_id, f"Email error: {str(e)}"), 200


@app.route("/send-sms", methods=["POST"])
def send_sms_tool():
    data = request.json or {}
    tool_call_id, _, args = extract_tool_call(data)
    phone = normalize_phone(get_caller_phone(data) or args.get("phone", ""))
    req_type = str(args.get("type", "website")).lower()
    link = SERVICE_LINKS.get(req_type, SERVICE_LINKS["website"])

    if not phone:
        return tool_result(tool_call_id, "No phone number available from caller ID."), 200
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
        return tool_result(tool_call_id, "SMS system not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER."), 200

    message_body = f"Photo Illusions: Here is your {req_type} link: {link}"

    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=phone,
        )
        if msg.sid:
            return tool_result(tool_call_id, "SMS sent successfully."), 200
        return tool_result(tool_call_id, "SMS send returned no confirmation."), 200
    except Exception as e:
        return tool_result(tool_call_id, f"SMS error: {str(e)}"), 200


@app.route("/request-callback", methods=["POST"])
def request_callback():
    data = request.json or {}
    tool_call_id, _, args = extract_tool_call(data)
    caller_phone = get_caller_phone(data)

    caller_name = args.get("caller_name", "Unknown caller")
    message = args.get("message", "Callback requested")
    requested_staff = args.get("requested_staff", "Any available")
    urgency = args.get("urgency", "normal")

    urgency_label = "🔴 URGENT" if urgency == "high" else "📞 Normal"

    subject = f"{urgency_label} Callback Request — {caller_name}"
    body = (
        f"Callback Request\n"
        f"{'=' * 40}\n"
        f"Urgency: {urgency_label}\n"
        f"Caller: {caller_name}\n"
        f"Phone: {caller_phone or 'Unknown'}\n"
        f"Requested Staff: {requested_staff}\n"
        f"Message: {message}\n"
        f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"{'=' * 40}\n"
        f"Please call back as soon as possible."
    )

    sent = False
    try:
        if EMAIL_RECEIVER:
            sent = send_email(EMAIL_RECEIVER, subject, body)
    except Exception:
        pass

    # Also try SMS to owner
    try:
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and OWNER_PHONE_NUMBER:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            sms_body = f"{urgency_label} callback: {caller_name} ({caller_phone}) wants {requested_staff} to call back. Msg: {message}"
            client.messages.create(body=sms_body, from_=TWILIO_PHONE_NUMBER, to=OWNER_PHONE_NUMBER)
    except Exception:
        pass

    if sent:
        return tool_result(tool_call_id, f"Callback request sent to the team. {caller_name} will receive a call back."), 200
    return tool_result(tool_call_id, "Callback request noted. The team will be notified."), 200


@app.route("/transfer-to-human", methods=["POST"])
def transfer_to_human():
    data = request.json or {}
    tool_call_id, _, args = extract_tool_call(data)
    caller_phone = get_caller_phone(data)

    # Notify the team that a transfer was requested
    try:
        if EMAIL_RECEIVER:
            send_email(
                EMAIL_RECEIVER,
                f"🔁 Live Transfer Requested — {caller_phone}",
                f"A caller ({caller_phone}) requested to speak with a live representative.\n"
                f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"Please call them back immediately."
            )
    except Exception:
        pass

    # Try SMS to owner for immediate attention
    try:
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and OWNER_PHONE_NUMBER:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=f"🔁 Live transfer requested by {caller_phone}. Please call them now.",
                from_=TWILIO_PHONE_NUMBER,
                to=OWNER_PHONE_NUMBER,
            )
    except Exception:
        pass

    return tool_result(tool_call_id, "Transfer request sent. Tell the caller someone will be with them shortly or will call right back."), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    if data.get("message", {}).get("type") == "end-of-call-report":
        try:
            call = data.get("message", data)
            summary = call.get("summary", "No summary.")
            transcript = call.get("transcript", "No transcript.")
            if EMAIL_RECEIVER:
                send_email(EMAIL_RECEIVER, "Photo Illusions Call Report", f"Summary:\n{summary}\n\nTranscript:\n{transcript}")
        except Exception:
            print(f"Webhook report error: {traceback.format_exc()}")
    return jsonify({"status": "OK"}), 200


@app.route("/call-logs", methods=["GET"])
def call_logs():
    """Pull recent call logs from Vapi API. Optional query params: ?limit=20&days=7"""
    if not VAPI_PRIVATE_KEY:
        return jsonify({"error": "VAPI_PRIVATE_KEY not configured"}), 500

    limit = request.args.get("limit", "50", type=str)
    days = request.args.get("days", "7", type=str)

    try:
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=int(days))).isoformat() + "Z"

        headers = {"Authorization": f"Bearer {VAPI_PRIVATE_KEY}"}
        params = {"limit": limit, "createdAtGe": cutoff}
        resp = requests.get("https://api.vapi.ai/call", headers=headers, params=params, timeout=15)

        if resp.status_code != 200:
            return jsonify({"error": f"Vapi API returned {resp.status_code}", "detail": resp.text}), resp.status_code

        calls = resp.json()
        # Summarize each call
        summary = []
        for c in calls:
            summary.append({
                "id": c.get("id"),
                "created": c.get("createdAt"),
                "ended": c.get("endedAt"),
                "duration_sec": c.get("costs", [{}])[0].get("minutes", 0) * 60 if c.get("costs") else None,
                "status": c.get("status"),
                "ended_reason": c.get("endedReason"),
                "customer_phone": c.get("customer", {}).get("number"),
                "transcript": c.get("transcript"),
                "summary": c.get("summary"),
                "messages": c.get("messages"),
            })

        return jsonify({"count": len(summary), "calls": summary}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/incoming-sms", methods=["POST"])
def incoming_sms():
    """Handle incoming SMS replies from customers and forward to business email."""
    from_number = request.form.get("From", "Unknown")
    body = request.form.get("Body", "")
    to_number = request.form.get("To", "")

    # Look up customer in CRM
    normalized = normalize_phone(from_number)
    crm = load_crm()
    customer = crm.get(normalized, {})
    customer_name = customer.get("name", "Unknown Customer")

    subject = f"Text from {customer_name} ({from_number})"
    email_body = (
        f"Incoming text message to Photo Illusions\n"
        f"{'='*40}\n\n"
        f"From: {customer_name}\n"
        f"Phone: {from_number}\n"
        f"To: {to_number}\n"
        f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"Message:\n{body}\n\n"
        f"{'='*40}\n"
        f"Reply to this customer by texting {from_number} from your Twilio console\n"
        f"or go to: https://console.twilio.com/us1/develop/sms/try-it-out/send-an-sms"
    )

    try:
        if EMAIL_RECEIVER:
            send_email(EMAIL_RECEIVER, subject, email_body)
    except Exception:
        print(f"Incoming SMS email forward error: {traceback.format_exc()}")

    # Forward to owner's cell phone via SMS
    try:
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and OWNER_PHONE_NUMBER:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            forward_msg = f"📩 Text from {customer_name} ({from_number}):\n\n{body}"
            client.messages.create(
                body=forward_msg,
                from_=TWILIO_PHONE_NUMBER,
                to=OWNER_PHONE_NUMBER,
            )
    except Exception:
        print(f"Incoming SMS phone forward error: {traceback.format_exc()}")

    # Auto-reply acknowledging receipt
    twiml_response = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Message>Thanks for texting Photo Illusions! We got your message and will reply shortly. 📸</Message>"
        "</Response>"
    )
    return twiml_response, 200, {"Content-Type": "text/xml"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
