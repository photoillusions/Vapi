import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURATION ---
# On Render, these come from Environment Variables.
# For local testing, you can hardcode them temporarily (but don't share this file if you do!)
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "your_email@gmail.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "your_gmail_app_password")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "your_email@gmail.com")

@app.route('/', methods=['GET'])
def home():
    return "Vapi Email Server is Running!"

@app.route('/webhook', methods=['POST'])
def vapi_webhook():
    data = request.json
    print("Received data from Vapi:", data)  # Logs to Render console

    # Vapi sends different message types. We only want the call report.
    message_type = data.get('message', {}).get('type')
    
    # Depending on Vapi version, it might be 'end-of-call-report' or just the data structure
    # We check if 'call' or 'message' exists.
    
    if message_type == 'end-of-call-report' or data.get('message', {}).get('type') == 'end-of-call-report':
        send_email_notification(data)
        return jsonify({"status": "Email sent"}), 200
    
    # Fallback: sometimes Vapi sends the report directly in the root
    if 'transcript' in data or 'summary' in data:
        send_email_notification(data)
        return jsonify({"status": "Email sent"}), 200

    return jsonify({"status": "Ignored"}), 200

def send_email_notification(data):
    try:
        # Extract details from Vapi JSON
        # Note: The structure depends on your specific Vapi output settings
        call_details = data.get('message', data)
        transcript = call_details.get('transcript', 'No transcript available.')
        summary = call_details.get('summary', 'No summary available.')
        recording_url = call_details.get('recordingUrl', 'No recording.')
        
        # Customer number check
        customer = call_details.get('customer', {}).get('number', 'Unknown Number')

        # Create Email
        subject = f"📞 Vapi Call Finished: {customer}"
        body = f"""
        <h2>New Call Report</h2>
        <p><strong>Caller:</strong> {customer}</p>
        <p><strong>Summary:</strong> {summary}</p>
        <hr>
        <h3>Transcript:</h3>
        <p>{transcript}</p>
        <hr>
        <p><a href="{recording_url}">🎧 Listen to Recording</a></p>
        """

        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        # Send via Gmail SMTP
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")

    except Exception as e:
        print(f"❌ Failed to send email: {e}")

if __name__ == '__main__':
    # Run locally on port 5000
    app.run(host='0.0.0.0', port=5000)