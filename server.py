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

# --- LINKS DATABASE (Update these!) ---
LINKS = {
    "contract": "https://www.photoillusions.us/contract",
    "payment": "https://dashboard.stripe.com/acct_1AN9bKKAiHY3duEM/payments",
    "website": "https://www.photoillusions.us",
    "gallery": "https://www.photoillusions.us/gallery",
    "booking": "https://www.cognitoforms.com/photoillusions1/photoillusionseventregistration",
    "form": "https://www.photoillusions.us/general-form"
}

@app.route('/', methods=['GET'])
def home():
    return "Vapi Helper (Email + SMS) is Online"

# --- 1. SEND SMS TOOL (Triggered by AI during call) ---
@app.route('/send-sms', methods=['POST'])
def send_sms_tool():
    data = request.json
    print(f"📩 SMS Request: {data}")

    # Handle Vapi's different tool payload structures
    args = {}
    tool_call_id = "unknown"
    
    try:
        # Check if arguments are nested (Standard Tool)
        if 'message' in data and 'toolCalls' in data['message']:
            tool_call = data['message']['toolCalls'][0]
            args = tool_call['function']['arguments']
            tool_call_id = tool_call['id']
        else:
            # Check if arguments are flat (Custom Tool fallback)
            args = data
    except:
        args = data

    phone = args.get('phone')
    req_type = args.get('type', 'website').lower()

    if not phone:
        return jsonify({"results": [{"toolCallId": tool_call_id, "result": "Error: Missing phone number"}]}), 400

    link = LINKS.get(req_type, LINKS['website'])
    body = f"Hello from Photo Illusions! Here is the {req_type} link: {link}"

    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        # Twilio requires the number to have a + sign
        if not phone.startswith('+'): phone = f"+{phone}"
        
        msg = client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=phone)
        print(f"✅ SMS Sent: {msg.sid}")
        
        return jsonify({
            "results": [{
                "toolCallId": tool_call_id,
                "result": f"Success! Sent {req_type} link."
            }]
        }), 200
    except Exception as e:
        print(f"❌ Twilio Error: {e}")
        return jsonify({
            "results": [{
                "toolCallId": tool_call_id,
                "result": f"Failed to send SMS. Error: {str(e)}"
            }]
        }), 500

# --- 2. EMAIL NOTIFICATION (Triggered after call ends) ---
@app.route('/webhook', methods=['POST'])
def vapi_email_webhook():
    data = request.json
    # Only send email if the call is actually finished
    msg_type = data.get('message', {}).get('type', '')
    
    if msg_type == 'end-of-call-report':
        send_email_notification(data)
        return jsonify({"status": "Email sent"}), 200
    
    return jsonify({"status": "Ignored"}), 200

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
        msg['Subject'] = f"📞 Call: {customer}"
        
        body = f"""
        <h3>New Call Finished</h3>
        <p><strong>Customer:</strong> {customer}</p>
        <p><strong>Summary:</strong> {summary}</p>
        <p><a href="{recording}">🎧 Listen to Recording</a></p>
        <hr>
        <p><strong>Transcript:</strong><br>{transcript}</p>
        """
        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent")
    except Exception as e:
        print(f"❌ Email Error: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
