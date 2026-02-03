import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURATION ---
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")
# We don't need Twilio keys anymore!
# TEXTBELT_KEY = os.environ.get("TEXTBELT_KEY", "textbelt") # Use "textbelt" for free test

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
    return "Master Vapi Server Online (Textbelt Edition)"

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
                "endpointing": 1500  # Waits 1.5 seconds before responding
            },
             "voice": {
                "provider": "11labs",
                "voiceId": "burt"
            }
        }
    }
    return jsonify(response), 200

# --- 2. SMS TOOL (Textbelt Version) ---
@app.route('/send-sms', methods=['POST'])
def send_sms_tool():
    data = request.json
    print(f"📩 SMS Triggered")

    # 1. AUTO-DETECT PHONE NUMBER
    system_phone = None
    try:
        system_phone = data.get('message', {}).get('call', {}).get('customer', {}).get('number')
        if not system_phone:
             system_phone = data.get('message', {}).get('customer', {}).get('number')
    except: pass
    
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

    # FORCE USE OF SYSTEM PHONE
    phone = system_phone if system_phone else args.get('phone')
    req_type = args.get('type', 'website').lower()
    
    print(f"🕵️ Sending to: {phone} for {req_type}")

    if not phone or len(phone) < 10:
        return jsonify({"results": [{"toolCallId": tool_call_id, "result": "Error: Phone number invalid or missing."}]}), 200

    link = LINKS.get(req_type, LINKS['website'])
    message_body = f"Hello from Photo Illusions! Here is the {req_type} link: {link}"
    
    # --- TEXTBELT MAGIC HERE ---
    try:
        resp = requests.post('https://textbelt.com/text', {
            'phone': phone,
            'message': message_body,
            'key': 'textbelt', # Use 'textbelt' for free daily test. Buy a key for real use.
        })
        print(f"Textbelt Response: {resp.json()}")
        
        return jsonify({"results": [{"toolCallId": tool_call_id, "result": "SMS Sent Successfully via Textbelt"}]}), 200
    except Exception as e:
        print(f"❌ SMS Error: {e}")
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
