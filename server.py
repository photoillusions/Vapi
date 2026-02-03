import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from twilio.rest import Client

app = Flask(__name__)

# --- CONFIGURATION ---
# Email Keys (Already set in Render)
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

# Twilio Keys (You will add these next)
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

# --- DATABASE OF LINKS ---
# UPDATE THESE with your real links!
LINKS = {
    "reservation": "https://photo-illusions-customer-registration.onrender.com/Form.html",
    "payment": "https://photo-illusions-customer-registration.onrender.com/Form.html",
    "website": "https://www.photoillusions.us",
    "gallery": "https://www.photoillusions.us/gallery",
    "packages": "https://photoillusions.github.io/photo-illusions-flyer/",
}

@app.route('/', methods=['GET'])
def home():
    return "Vapi Command Center (Email + SMS) is Running!"

# --- EMAIL WEBHOOK (Existing) ---
@app.route('/webhook', methods=['POST'])
def vapi_email_webhook():
    data = request.json
    # Check for end-of-call report
    if data.get('message', {}).get('type') == 'end-of-call-report':
        send_email_notification(data)
        return jsonify({"status": "Email sent"}), 200
    return jsonify({"status": "Ignored"}), 200

# --- SMS TOOL (New) ---
@app.route('/send-sms', methods=['POST'])
def send_sms_tool():
    data = request.json
    print("SMS Request:", data)
    
    # Extract arguments from Vapi tool call
    tool_call = data.get('message', {}).get('toolCalls', [{}])[0]
    args = tool_call.get('function', {}).get('arguments', {})
    
    # Fallback if Vapi sends arguments directly
    if not args: args = data

    phone_number = args.get('phone')
    request_type = args.get('type', 'website').lower() # contract, payment, etc.
    
    if not phone_number:
        return jsonify({"result": "Error: No phone number provided"}), 400

    # 1. Get the correct link
    link = LINKS.get(request_type, LINKS['website'])
    
    # 2. Craft the message
    message_body = f"Hello from Photo Illusions! Here is the {request_type} link you requested: {link}"
    
    # 3. Send via Twilio
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        message = client.messages.create(
            body=message_body,
            from_=TWILIO_FROM_NUMBER,
            to=phone_number
        )
        print(f"SMS sent to {phone_number}: {message.sid}")
        
        return jsonify({
            "results": [{
                "toolCallId": tool_call.get('id'),
                "result": f"Successfully sent {request_type} link to user."
            }]
        }), 200
        
    except Exception as e:
        print(f"Twilio Error: {e}")
        return jsonify({
            "results": [{
                "toolCallId": tool_call.get('id'),
                "result": f"Failed to send SMS: {str(e)}"
            }]
        }), 500

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
    except Exception as e:
        print(f"Email Error: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

