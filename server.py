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
TEXTBELT_KEY = os.environ.get("TEXTBELT_KEY")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

CRM_STORE_PATH = os.path.join(os.path.dirname(__file__), "crm_store.json")

SERVICE_LINKS = {
    "website": "photoillusions.us",
    "booking": "photoillusions.us/book",
    "payment": "photoillusions.us/pay",
    "contract": "photoillusions.us/contract",
    "portfolio": "photoillusions.us/gallery",
}

SYSTEM_PROMPT = """
# Photo Illusions — AI Booking Concierge
You are Mary, the AI assistant for Photo Illusions.

## Tone
- Warm, polished, professional, and conversion-focused.
- Speak at a measured, unhurried pace — never rush.
- Ask one question at a time.
- Guide callers naturally toward booking and deposit.

## Critical rules
- You already have the caller's phone from caller ID. NEVER ask for phone number.
- If customer asks for links (booking, payment, contract, portfolio), call send_sms_link tool immediately.
- Never read card numbers aloud.
- If tool errors occur, say: "I'm having a quick system issue. Let me take your details and our team will follow up right away."
- If a caller says they did not receive a confirmation email or booking email, ask for their name and email address, then call send_booking_email or send_service_info_email to resend it.

## Services
- Portrait sessions
- Event photography coverage
- Video add-ons
- On-location + studio options

## Booking flow
1) Identify service type and requested date/time.
2) Call check_availability.
3) If available, collect name and email.
4) Call book_appointment to pencil in or confirm.
5) If customer is ready to lock date, collect card fields one at a time and call process_payment.
6) After successful payment, call send_booking_email.

## Payments
- Deposit is required to lock date.
- Use process_payment only when caller is ready.

## Returning customers
- Call lookup_customer first after getting their name.
- If found, personalize with prior context.
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
            "textbelt_key": mask(TEXTBELT_KEY),
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
            "firstMessage": "Hello, this is Mary, Photo Illusions AI Assistant. How may I help you today?",
            "model": {
                "provider": "openai",
                "model": "gpt-5-mini",
                "messages": [{"role": "system", "content": prompt}],
                "tools": [
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
                ],
            },
            "serverMessages": ["end-of-call-report"],
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "en-US",
                "endpointing": 1500,
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "EXAVITQu4vr4xnSDxMaL",
                "stability": 0.5,
                "similarityBoost": 0.75,
                "speed": 0.92,
            },
        }
    }
    return jsonify(response), 200


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
    if not TEXTBELT_KEY:
        return tool_result(tool_call_id, "SMS system not configured. Add TEXTBELT_KEY."), 200

    message_body = f"Photo Illusions: Here is your {req_type} link: {link}"

    try:
        resp = requests.post(
            "https://textbelt.com/text",
            {
                "phone": phone,
                "message": message_body,
                "key": TEXTBELT_KEY,
            },
            timeout=20,
        )
        payload = resp.json()
        if payload.get("success"):
            return tool_result(tool_call_id, "SMS sent successfully."), 200
        return tool_result(tool_call_id, f"SMS failed: {payload.get('error', 'unknown error')}"), 200
    except Exception as e:
        return tool_result(tool_call_id, f"SMS error: {str(e)}"), 200


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
