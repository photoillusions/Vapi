import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from twilio.rest import Client

app = Flask(__name__)

# --- CONFIGURATION ---
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

# --- LINKS ---
LINKS = {
    "contract": "https://www.photoillusions.us/contract",
    "payment": "https://dashboard.stripe.com/acct_1AN9bKKAiHY3duEM/payments",
    "website": "https://www.photoillusions.us",
    "gallery": "https://www.photoillusions.us/gallery",
    "booking": "https://www.cognitoforms.com/photoillusions1/photoillusionseventregistration",
    "form": "https://www.photoillusions.us/general-form"
}

# --- THE BRAIN (Instructions) ---
SYSTEM_PROMPT = """
You are the AI Receptionist for Photo Illusions.
BEHAVIOR:
1. You are warm, professional, and concise.
2. IMPORTANT: You already HAVE the customer's phone number from Caller ID. NEVER ask for it.
3. If they want a contract, payment link, or booking form, just say: "I've sent that to your phone now."
4. Immediately use the 'send_sms_link' tool.
"""

@app.route('/', methods=['GET'])
def home():
    return "Master Vapi Server Online"

# --- 1. CALL SETTINGS (Runs when phone rings) ---
@app.route('/inbound', methods=['POST'])
def inbound_call():
    print("📞 Incoming Call - Loading Settings...")
    response = {
        "assistant": {
            "firstMessage": "Thank you for calling Photo Illusions. How can I help you today?",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "send_sms_link",
                            "description": "Sends a text message with a link.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "phone": {"type": "string", "description": "Customer phone number"},
                                    "type": {"type": "string", "enum": ["contract", "payment", "website", "booking", "form"]}
                                },
                                "required": ["phone", "type"]
                            }
                        },
                        "server": {"url": "https://vapi-mvsk.onrender.com/send-sms"}
                    }
                ]
            },
            # --- THE PATIENCE FIX ---
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "en-US",
                "endpointing": 1200  # <--- THIS IS THE MAGIC NUMBER (1.2 seconds silence)
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "burt" # or your preferred voice ID
            }
        }
    }
    return jsonify(response), 200

# --- 2. SMS TOOL (Smart Caller ID) ---
@app.route('/send-sms', methods=['POST'])
def send_sms_tool():
    data = request.json
    print(f"📩 SMS Triggered")

    # Extract args
    args = {}
    tool_call_id = "unknown"
    try:
        if 'message' in data and 'toolCalls' in data['message']:
            tool_call = data['message']['toolCalls'][0]
            args = tool_call['function']['arguments']
            tool_call_id = tool_call['id']
        else:
            args = data
    except: args = data

    # AUTO-DETECT PHONE NUMBER
    phone = args.get('phone')
    if not phone or phone == "current":
        # Grab the real Caller ID from the Vapi call data
        try:
            phone = data.get('message', {}).get('call', {}).get('customer', {}).get('number')
            # Fallback location for some Vapi versions
            if not phone:
                 phone = data.get('message', {}).get('customer', {}).get('number')
        except: pass

    req_type = args.get('type', 'website').lower()
    
    if not phone:
        return jsonify({"results": [{"toolCallId": tool_call_id, "result": "Error: Could not find phone number"}]}), 200

    link = LINKS.get(req_type, LINKS['website'])
    body = f"Hello from Photo Illusions! Here is the {req_type} link: {link}"
    
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        if not phone.startswith('+'): phone = f"+{phone}"
        client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=phone)
        return jsonify({"results": [{"toolCallId": tool_call_id, "result": "SMS Sent Successfully"}]}), 200
    except Exception as e:
        print(f"Twilio Error: {e}")
        return jsonify({"results": [{"toolCallId": tool_call_id, "result": "Failed"}]}), 200

# --- 3. EMAIL REPORT ---
@app.route('/webhook', methods=['POST'])
def vapi_email_webhook():
    data = request.json
    if data.get('message', {}).get('type') == 'end-of-call-report':
        send_email_notification(data)
    return jsonify({"status": "OK"}), 200

def send_email_notification(data):
    try:
        call = data.get('message', data)
        transcript = call.get('transcript', 'No transcript.')
        summary = call.get('summary', 'No summary.')
        recording = call.get('recordingUrl', '#')
        customer = call.get('customer', {}).get('number', 'Unknown')
        
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = f"📞 Call Report: {customer}"
        msg.attach(MIMEText(f"Summary: {summary}\n\nTranscript: {transcript}\n\nRecording: {recording}", 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
    except: pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
