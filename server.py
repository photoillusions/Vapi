import os
from flask import Flask, request, jsonify
from twilio.rest import Client

app = Flask(__name__)

# --- CONFIGURATION ---
# Ensure these match your Render Environment Variables exactly
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER") # Must start with +1

# --- LINKS DATABASE ---
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
    return "Vapi SMS Server Online"

@app.route('/send-sms', methods=['POST'])
def send_sms_tool():
    data = request.json
    print(f"📩 Incoming Request: {data}")

    # 1. Extract Phone and Type
    # Vapi sometimes nests arguments, sometimes sends them flat. This handles both.
    args = {}
    if 'message' in data and 'toolCalls' in data['message']:
        args = data['message']['toolCalls'][0]['function']['arguments']
        tool_call_id = data['message']['toolCalls'][0]['id']
    else:
        args = data
        tool_call_id = "unknown"

    phone = args.get('phone')
    req_type = args.get('type', 'website').lower()

    if not phone:
        return jsonify({"results": [{"toolCallId": tool_call_id, "result": "Error: Missing phone number"}]}), 400

    # 2. Get the Link
    link = LINKS.get(req_type, LINKS['website'])
    body = f"Hello from Photo Illusions! Here is the {req_type} link: {link}"

    # 3. Send Text
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        message = client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=phone)
        print(f"✅ SMS Sent to {phone}: {message.sid}")
        
        return jsonify({
            "results": [{
                "toolCallId": tool_call_id,
                "result": f"Success! Text sent for {req_type}."
            }]
        }), 200
    except Exception as e:
        print(f"❌ Twilio Error: {e}")
        return jsonify({
            "results": [{
                "toolCallId": tool_call_id,
                "result": "Failed to send text."
            }]
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
