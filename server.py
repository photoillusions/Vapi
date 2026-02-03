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
# Note: Textbelt uses "textbelt" as the key for free testing (1 per day)

# --- LINKS ---
LINKS = {
    "contract": "https://www.photoillusions.us/contract",
    "payment": "https://dashboard.stripe.com/acct_1AN9bKKAiHY3duEM/payments",
    "website": "https://www.photoillusions.us",
    "gallery": "https://www.photoillusions.us/gallery",
    "booking": "https://www.cognitoforms.com/photoillusions1/photoillusionseventregistration",
    "form": "https://www.photoillusions.us/general-form"
}

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
    return "Textbelt Server Online"

@app.route('/inbound', methods=['POST'])
def inbound_call():
    print("📞 Incoming Call")
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
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "en-US",
                "endpointing": 1500 # Wait 1.5s (Patience Fix)
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "burt"
            }
        }
    }
    return jsonify(response), 200

@app.route('/send-sms', methods=['POST'])
def send_sms_tool():
    data = request.json
    print(f"📩 SMS Triggered")

    # 1. SMART NUMBER DETECTION
    system_phone = None
    try:
        system_phone = data.get('message', {}).get('call', {}).get('customer', {}).get('number')
        if not system_phone:
             system_phone = data.get('message', {}).get('customer', {}).get('number')
    except: pass
    
    args = {}
    try:
        if 'message' in data and 'toolCalls' in data['message']:
            args = data['message']['toolCalls'][0]['function']['arguments']
        else:
            args = data
    except: args = data

    # Prioritize System Caller ID
    phone = system_phone if system_phone else args.get('phone')
    
    # 2. FIX US PHONE NUMBERS (The "Invalid Number" Fix)
    if phone:
        phone = str(phone).replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        # If it's 10 digits (856...), add +1
        if len(phone) == 10:
            phone = f"+1{phone}"
        # If it's 11 digits starting with 1 (1856...), add +
        elif len(phone) == 11 and phone.startswith("1"):
            phone = f"+{phone}"

    req_type = args.get('type', 'website').lower()
    link = LINKS.get(req_type, LINKS['website'])
    
    print(f"🕵️ Sending via Textbelt to: {phone}")

    if not phone:
        return jsonify({"result": "Error: No phone number found"}), 200

    # 3. SEND VIA TEXTBELT
    try:
        resp = requests.post('https://textbelt.com/text', {
            'phone': phone,
            'message': f"Hello from Photo Illusions! Here is your {req_type} link: {link}",
            'key': 'textbelt', # FREE KEY (1 per day). Buy a real key at textbelt.com if you like it.
        })
        print(f"Textbelt Result: {resp.text}")
        return jsonify({"result": "SMS Sent"}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"result": "Failed"}), 200

@app.route('/webhook', methods=['POST'])
def vapi_email_webhook():
    # EMAIL REPORTING
    data = request.json
    if data.get('message', {}).get('type') == 'end-of-call-report':
        try:
            call = data.get('message', data)
            summary = call.get('summary', 'No summary.')
            
            msg = MIMEMultipart()
            msg['From'] = EMAIL_SENDER
            msg['To'] = EMAIL_RECEIVER
            msg['Subject'] = f"📞 Call Report"
            msg.attach(MIMEText(f"Summary: {summary}", 'plain'))
            
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
            server.quit()
        except: pass
    return jsonify({"status": "OK"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
