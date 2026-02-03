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
# UPDATE THESE with your real links!
LINKS = {
    "contract": "https://www.photoillusions.us/contract",
    "payment": "https://dashboard.stripe.com/acct_1AN9bKKAiHY3duEM/payments",
    "website": "https://www.photoillusions.us",
    "gallery": "https://www.photoillusions.us/gallery",
    "booking": "https://www.cognitoforms.com/photoillusions1/photoillusionseventregistration",
    "form": "https://www.photoillusions.us/general-form"
}

# --- SYSTEM PROMPT (The Brain) ---
SYSTEM_PROMPT = """
You are the AI Receptionist for Photo Illusions, a premier event photography company.
Your goal is to help customers book events, check availability, and get contracts.

KEY BEHAVIORS:
1. Be professional, warm, and concise.
2. If they want to book, ask for the Date and Location.
3. If they ask for a contract, payment link, or form, use the 'send_sms_link' tool immediately.
   Say: "I've just sent that link to your phone."

SMS INSTRUCTIONS:
- Never read URLs out loud.
- Always use the tool to send them.
"""

@app.route('/', methods=['GET'])
def home():
    return "Vapi Brain is Running!"

# --- 1. INBOUND CALL HANDLER ---
# This is what Vapi hits when the phone rings.
@app.route('/inbound', methods=['POST'])
def inbound_call():
    print("📞 New Call Incoming - Loading Assistant Config")
    
    response = {
        "assistant": {
            "firstMessage": "Thank you for calling Photo Illusions. How can I help you today?",
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
                        "async": False,
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
                        },
                        # IMPORTANT: Pointing the tool back to THIS server
                        "server": {
                            "url": "https://vapi-mvsk.onrender.com/send-sms"
                        }
                    }
                ]
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "burt"
            }
        }
    }
    return jsonify(response), 200

# --- 2. SMS TOOL HANDLER ---
@app.route('/send-sms', methods=['POST'])
def send_sms_tool():
    print("🚀 SMS Tool Triggered!")
    data = request.json
    
    # Handle Vapi's different argument structures
    args = {}
    tool_call_id = "unknown"
    
    try:
        if 'message' in data and 'toolCalls' in data['message']:
            args = data['message']['toolCalls'][0]['function']['arguments']
            tool_call_id = data['message']['toolCalls'][0]['id']
        else:
            args = data
    except:
        args = data

    phone = args.get('phone')
    req_type = args.get('type', 'website').lower()
    
    print(f"Attempting to send {req_type} to {phone}")

    if not phone: 
        return jsonify({"results": [{"toolCallId": tool_call_id, "result": "Error: No phone number"}]}), 200

    link = LINKS.get(req_type, LINKS['website'])
    body = f"Hello from Photo Illusions! Here is the {req_type} link: {link}"
    
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=phone)
        print(f"✅ SMS Sent! SID: {msg.sid}")
        return jsonify({
            "results": [
                {
                    "toolCallId": tool_call_id,
                    "result": "SMS Sent successfully"
                }
            ]
        }), 200
    except Exception as e:
        print(f"❌ Twilio Error: {e}")
        return jsonify({
            "results": [
                {
                    "toolCallId": tool_call_id,
                    "result": f"Error sending SMS: {str(e)}"
                }
            ]
        }), 200

# --- 3. EMAIL REPORTER ---
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
        
        body = f"""
        <h2>New Call Finished</h2>
        <p><strong>Customer:</strong> {customer}</p>
        <p><strong>Summary:</strong> {summary}</p>
        <p><a href="{recording}">🎧 Listen to Recording</a></p>
        <hr>
        <h3>Transcript</h3>
        <p>{transcript}</p>
        """
        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
    except: pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
