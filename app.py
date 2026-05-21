from flask import Flask, render_template, request, jsonify, redirect
import requests
import os
import random
import datetime
import resend
import firebase_admin
import requests
import hmac
import hashlib
import uuid
import json
from base64 import b64encode
from firebase_admin import credentials, firestore, initialize_app
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter

# Load environment variables
load_dotenv(override=True)

resend.api_key = os.getenv("RESEND_API_KEY")

app = Flask(__name__)

# Hubtel SMS Auth
HUB_ID = os.getenv('HUBTEL_CLIENT_ID')
HUB_SECRET = os.getenv('HUBTEL_CLIENT_SECRET')
HUB_AUTH = b64encode(f"{HUB_ID}:{HUB_SECRET}".encode()).decode()


# --- SECURE TEST CREDENTIALS & CONFIGURATION 
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')

# Admin Access
ADMIN_ID = os.environ.get("ADMIN_ID")
ADMIN_PIN = os.environ.get("ADMIN_PIN")

ADMIN_EMAILS = ["ledghold.business@gmail.com"]

# Compliance & Entity Logic
COMPLIANCE_MODE = False
APP_ID = os.getenv('__app_id', 'ledgehold-ghana1')

def send_professional_sms(to_number, message_content):
    url = "https://smsc.hubtel.com/v1/messages/send"
    
    # Utilizing your exact pre-calculated Base64 authentication token
    headers = {
        "Authorization": f"Basic {HUB_AUTH}",
        "Content-Type": "application/json"
    }
    
    # Hubtel's strict JSON payload specifications (Must be TitleCase)
    payload = {
        "From": "Ledgehold",
        "To": to_number,
        "Content": message_content
    }
    
    try:
        # Firing as a JSON POST request with your headers
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        
        # Hubtel returns 200 or 201 when header-based JSON messages are accepted
        if response.status_code == 200 or response.status_code == 201:
            return True
        else:
            print(f"❌ Hubtel API Rejected Payload ({response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Hubtel Connection Exception: {str(e)}")
        return False

def send_handoff_email(order_data, paystack_ref):
    """Triggers an internal audit email via Resend once handoff is confirmed."""
    try:
        # Construct a professional HTML body
        email_body = f"""
        <div style="font-family: sans-serif; color: #333; max-width: 600px;">
            <h2 style="color: #22c55e;">Vault Released: Handshake Successful</h2>
            <p>The Gatekeeper has verified the device signature and authorized the payout for the following transaction:</p>
            
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                <tr style="background: #f8fafc;">
                    <td style="padding: 10px; border: 1px solid #e2e8f0;"><strong>Item</strong></td>
                    <td style="padding: 10px; border: 1px solid #e2e8f0;">{order_data.get('item', 'N/A')}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #e2e8f0;"><strong>Amount</strong></td>
                    <td style="padding: 10px; border: 1px solid #e2e8f0;">GHS {order_data.get('amount', 0)}</td>
                </tr>
                <tr style="background: #f8fafc;">
                    <td style="padding: 10px; border: 1px solid #e2e8f0;"><strong>Reference</strong></td>
                    <td style="padding: 10px; border: 1px solid #e2e8f0;"><code>{paystack_ref}</code></td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #e2e8f0;"><strong>Buyer Phone</strong></td>
                    <td style="padding: 10px; border: 1px solid #e2e8f0;">{order_data.get('buyerPhone', 'N/A')}</td>
                </tr>
            </table>
            
            <p style="font-size: 12px; color: #64748b;">This is an automated audit log for Ledgehold.</p>
        </div>
        """

        resend.Emails.send({
            "from": "Ledgehold System <onboarding@resend.dev>", # Use your verified Resend domain
            "to": ["ledgehold.business@gmail.com"], # Where you want to receive the alerts
            "subject": f"✅ Handoff Complete: {order_data.get('item')}",
            "html": email_body
        })
        print(f"📧 Resend: Handoff alert dispatched for {paystack_ref}")
        
    except Exception as e:
        print(f"⚠️ Resend Integration Error: {str(e)}")


# --- FIREBASE INFRASTRUCTURE HANDSHAKE --- (PRESERVED)
def get_firebase_context():
    """Consolidated context provider for frontend templates"""
    return {
        "__app_id": APP_ID,
        "__firebase_config": os.environ.get("__firebase_config", "{}"),
        "IMGBB_API_KEY": os.environ.get("IMGBB_API_KEY", ""),
        "compliance_mode": COMPLIANCE_MODE
    }

# Initialization Safety Guard
if not firebase_admin._apps:
    prod_cred_path = "/etc/secrets/service-account.json"
    local_cred_path = "service-account.json"

    if os.path.exists(prod_cred_path):
        cred = credentials.Certificate(prod_cred_path)
        print("Security Protocol: Production Node Active")
    elif os.path.exists(local_cred_path):
        cred = credentials.Certificate(local_cred_path)
        print("Security Protocol: Local Node Active")
    else:
        cred = None
        print("Warning: No service-account.json found.")

    if cred:
        initialize_app(cred)
    else:
        initialize_app()

db = firestore.client()

# --- CONTEXT PROCESSOR --- (PRESERVED)
@app.context_processor
def inject_globals():
    return dict(compliance_mode=COMPLIANCE_MODE)

# --- UTILITIES ---

def validate_request(data, required_fields):
    """Validates that all required fields are present and non-empty"""
    if not data:
        return False, "Request body is empty"
    for field in required_fields:
        value = data.get(field)
        if value is None or str(value).strip() == '':
            return False, f"Missing or empty required field: {field}"
    return True, None

def normalize_app_id(app_id):
    """Normalizes appId to prevent artifacts/None paths"""
    if not app_id:
        return None
    return str(app_id).strip().lower()

def run_expiry_sweep():
    print(f"🧹 Starting 120-Hour Expiry Sweep at {datetime.datetime.now()}...")
    
    orders_ref = db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('orders')
    
    # Target all currently active escrow orders
    query = orders_ref.where(filter=FieldFilter('status', '==', 'paid_in_escrow')).get()
    
    expired_count = 0
    now = datetime.datetime.now(datetime.timezone.utc)
    
    for doc in query:
        data = doc.to_dict()
        created_at = data.get('createdAt')
        
        if created_at:
            # Convert Firestore timestamp to standard datetime
            order_time = created_at.replace(tzinfo=datetime.timezone.utc)
            time_diff = now - order_time
            
            # If the order is older than 5 days (120 hours)
            if time_diff.total_seconds() > (168 * 3600):
                print(f"⚠️ Flagging Order {doc.id} for Administrative Review (Expired 120h).")
                doc.reference.update({"status": "requires_review"})
                expired_count += 1
                
    print(f"✅ Sweep Complete. Flagged {expired_count} dead transactions.")

if __name__ == "__main__":
    run_expiry_sweep()

# --- ROUTES --- (PRESERVED)

@app.route('/')
def home():
    source = request.args.get('ref')
    welcome_msg = None
    welcome_type = "info"

    if source == 'front':
        welcome_msg = "Curiosity rewarded! Explore our student specials."
        welcome_type = "success"
    elif source == 'back' or source == 'tshirt':
        welcome_msg = "Hey Scholar!  Check out our Student Specials below."
        welcome_type = "primary"

    food_is_active = datetime.datetime.now().weekday() >= 4
    return render_template('home.html',
                           welcome_msg=welcome_msg,
                           welcome_type=welcome_type,
                           food_active=food_is_active)

@app.route('/healthz')
def health_check():
    return "OK", 200

@app.route('/admin-auth', methods=['POST'])
def admin_auth():
    data = request.json
    if data.get('id') == ADMIN_ID and data.get('pin') == ADMIN_PIN:
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Unauthorized"}), 401

@app.route('/api/admin/send_sms', methods=['POST'])
def admin_send_sms():
    data = request.json
    phone = data.get('phone')
    message = data.get('message')

    # 1. Guard Clause
    if not phone or not message:
        print("SMS Error: Missing phone number or message content.")
        return jsonify({"success": False, "error": "Missing parameters"}), 400

    try:
        # 2. Format the phone number to international standard (233...) just in case
        clean_phone = str(phone).replace("+", "").replace(" ", "").strip()
        if clean_phone.startswith("0"):
            clean_phone = "233" + clean_phone[1:]

        # 3. Pull Hubtel Credentials from Render Environment Variables
        hubtel_client_id = os.environ.get('HUBTEL_CLIENT_ID')
        hubtel_client_secret = os.environ.get('HUBTEL_CLIENT_SECRET')
        sender_id = os.environ.get('HUBTEL_SENDER_ID', 'Ledgehold') # Defaults to Ledgehold if not set

        if not hubtel_client_id or not hubtel_client_secret:
            print("⚠️ SMS Warning: Hubtel credentials missing from environment. Bypassing send.")
            # We return success so the frontend doesn't crash during testing if env vars aren't set yet
            return jsonify({"success": True, "warning": "Simulated. No credentials."}), 200

        # 4. Fire the payload to Hubtel via their Quick Send API
        response = requests.get(
            "https://smsc.hubtel.com/v1/messages/send",
            params={
                "clientid": hubtel_client_id,
                "clientsecret": hubtel_client_secret,
                "from": sender_id,
                "to": clean_phone,
                "content": message
            }
        )

        # 5. Evaluate the gateway response directly via Hubtel's JSON
        try:
            res_data = response.json()
            
            # Verify success: HTTP OK AND Hubtel status indicates success
            # (Adjust based on Hubtel's actual API docs - common: status 0 = success)
            success = response.ok and res_data.get('status') in [0, 1, 100]  # ← FIXED
            
            if success:
                msg_id = res_data.get('messageId', 'Unknown')
                print(f"📨 SMS DISPATCHED: Success to {clean_phone} | Hubtel ID: {msg_id}")
                return jsonify({"success": True}), 200
            else:
                error_msg = res_data.get('message', 'Gateway rejected the message')
                print(f"❌ SMS Gateway Error: {error_msg}")
                return jsonify({"success": False, "error": error_msg}), 502
                
        except Exception as json_err:
            # Fallback for non-JSON response
            if response.ok:
                print(f"⚠️ SMS Sent but response not JSON: {response.text}")
                return jsonify({"success": True, "warning": "Response format unexpected"}), 200
            else:
                print(f"❌ SMS Gateway Error (Raw): {response.text}")
                return jsonify({"success": False, "error": "Gateway communication failed"}), 502

    except Exception as e:
        print(f"🛡️ SMS Pipeline Exception: {str(e)}")
        return jsonify({"success": False, "error": "Internal Processing Error"}), 500
    
@app.route('/api/email/dispatch', methods=['POST'])
def universal_email_dispatch():
    data = request.json
    action_type = data.get('type')  # Identifies what event just happened
    payload = data.get('payload', {}) # Holds the dynamic data (names, IDs, etc.)
    
    if not action_type:
        return jsonify({"success": False, "error": "Missing action type."}), 400

    subject = ""
    html_body = ""

    # ========================================================
    # SECURITY ACTION REGISTRY
    # ========================================================
    
    # Template 1: New Merchant KYC uploaded
    if action_type == "kyc_submitted":
        merchant_name = payload.get('fullName', 'Unknown Merchant')
        merchant_id = payload.get('merchantId', 'Unknown ID')
        university = payload.get('university', 'Unknown Campus')
        
        subject = f"👤 New Account: KYC Submitted ({merchant_id})"
        html_body = f"""
        <div style="font-family: sans-serif; padding: 20px; color: #0f172a;">
            <h3 style="color: #3b82f6; margin-top: 0;">New Merchant Registration Awaiting Review</h3>
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin-bottom: 20px;"/>
            <p><b>Name:</b> {merchant_name}</p>
            <p><b>Merchant ID:</b> {merchant_id}</p>
            <p><b>Institution:</b> {university}</p>
            <br/>
            <p><a href="https://market-place-gx9a.onrender.com/admin_controls" style="background: #0f172a; color: white; padding: 12px 24px; text-decoration: none; border-radius: 30px; font-weight: bold; font-size: 13px;">Open Admin Command Center</a></p>
        </div>
        """

    # Template 2: Advertisement Inquiry
    elif action_type == "ad_inquiry":
        business_name = payload.get('businessName', 'Unknown Business')
        contact_email = payload.get('email', 'N/A')
        contact_phone = payload.get('phone', 'N/A')
        
        subject = f"📢 Ad Inquiry: {business_name}"
        html_body = f"""
        <div style="font-family: sans-serif; padding: 20px; color: #0f172a;">
            <h3 style="color: #3b82f6; margin-top: 0;">New Advertisement Request</h3>
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin-bottom: 20px;"/>
            <p><b>Business Name:</b> {business_name}</p>
            <p><b>Email:</b> <a href="mailto:{contact_email}">{contact_email}</a></p>
            <p><b>Phone/WhatsApp:</b> {contact_phone}</p>
            <br/>
            <p style="font-size: 13px; color: #64748b;">Please reach out to this business to request necessary business info.</p>
        </div>
        """
    
    # Template 3: Premium Merchant Kit Order/Request
    elif action_type == "merch_request":
        merchant_id = payload.get('merchantId', 'Unknown Merchant')
        campus = payload.get('campus', 'Unknown Campus')
        pickup = payload.get('pickupPoint', 'Unknown Location')
        selection = payload.get('gearSelection', 'No gear specified')
        total_items = payload.get('totalItems', 1)
        
        subject = f"👕 [MERCH ORDER] - {merchant_id} ({total_items} Items)"
        html_body = f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; color: #0f172a;">
            <h3 style="color: #10b981; margin-top: 0; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">
                New Custom Gear Order
            </h3>
            <p style="margin-top: 15px;"><b>Merchant Identifier:</b> {merchant_id}</p>
            <p><b>Distribution Campus:</b> {campus}</p>
            <p><b>Fulfillment Pickup Point:</b> {pickup}</p>
            
            <h4 style="margin-top: 25px; margin-bottom: 10px; color: #475569; font-size: 12px; letter-spacing: 0.5px; text-transform: uppercase;">
                Gear Configuration Breakdown
            </h4>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 12px; font-size: 14px; line-height: 1.6;">
                {selection}
            </div>
            
            <p style="font-size: 11px; color: #94a3b8; margin-top: 30px; border-top: 1px dashed #e2e8f0; padding-top: 15px;">
                Fulfillment SLA: Standard 10-day production loop applies. Verify Paystack dashboard logs for corresponding matching reference tokens if premium add-ons exist.
            </p>
        </div>
        """

        # Template 4: Merchant Priority Support Ticket
    elif action_type == "merchant_support":
        merchant_id = payload.get('merchantId', 'Unknown/Logged Out')
        contact_email = payload.get('email', 'No email provided')
        issue_desc = payload.get('issue', 'No description provided')
        
        subject = f"🚨 SUPPORT TICKET - {merchant_id}"
        html_body = f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; color: #0f172a;">
            <h3 style="color: #ef4444; margin-top: 0; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">
                Priority Support Request
            </h3>
            <p style="margin-top: 15px;"><b>Merchant Account:</b> {merchant_id}</p>
            <p><b>Contact Email:</b> {contact_email}</p>
            
            <h4 style="margin-top: 25px; margin-bottom: 10px; color: #475569; font-size: 12px; letter-spacing: 0.5px; text-transform: uppercase;">
                Issue / Concern Log
            </h4>
            <div style="background: #fff1f2; border: 1px solid #fda4af; padding: 15px; border-radius: 12px; font-size: 14px; line-height: 1.6; color: #9f1239;">
                {issue_desc}
            </div>
            
            <p style="font-size: 11px; color: #94a3b8; margin-top: 30px; border-top: 1px dashed #e2e8f0; padding-top: 15px;">
                This ticket was generated via the Secure Dashboard Support Hub. Reply directly to the merchant's email address to initiate a resolution thread.
            </p>
        </div>
        """

    else:
        print(f"⚠️ Switchboard Warning: Unregistered action type '{action_type}'")
        return jsonify({"success": False, "error": "Template not found."}), 400

    # ========================================================
    # DISPATCH TO ADMINS
    # ========================================================
    try:
        response = resend.Emails.send({
            "from": "Ledgehold System <onboarding@resend.dev>", # Update with your verified Resend domain
            "to": ["ledgehold.business@gmail.com"], # Sends to both addresses instantly
            "subject": subject,
            "html": html_body
        })
        print(f"📧 ALERTS DISPATCHED: '{action_type}' email routed to Admin array.")
        return jsonify({"success": True}), 200
        
    except Exception as e:
        print(f"❌ Email Switchboard Exception: {str(e)}")
        return jsonify({"success": False, "error": "Internal server error."}), 500

@app.route('/admin_controls')
def admin_controls():
    return render_template('admin.html', **get_firebase_context())

@app.route('/api/marketplace/listings', methods=['GET'])
def get_all_listings():
    """
    Fetches real-time listings from the Firestore silo.
    Wires directly into the logic in the Canvas (marketplace.html).
    """
    try:
        # 1. Fetch Takedown Registry (Institutional Safety)
        # Path matches Rule 1: artifacts/{appId}/public/data/takedown_registry
        takedown_ref = db.collection('artifacts').document(APP_ID)\
                         .collection('public').document('data')\
                         .collection('takedown_registry')
        blocked_ids = [doc.id for doc in takedown_ref.stream()]

        # 2. Fetch Active Listings
        # Path matches Canvas: artifacts/{appId}/public/data/market_listings
        listings_ref = db.collection('artifacts').document(APP_ID)\
                         .collection('public').document('data')\
                         .collection('market_listings')
        
        all_items = []
        for doc in listings_ref.stream():
            data = doc.to_dict()
            # Safety Checks: Must be 'active' and NOT in the Takedown Registry
            if data.get('status') == 'active' and doc.id not in blocked_ids:
                data['id'] = doc.id
                all_items.append(data)

        # 3. Randomize the display to maintain a "busy" and fair market feel
        random.shuffle(all_items)

        return jsonify({
            "success": True, 
            "count": len(all_items),
            "listings": all_items
        })

    except Exception as e:
        print(f"Firestore Client Error: {e}")
        return jsonify({
            "success": False, 
            "error": "The Marketplace is currently re-syncing.",
            "listings": []
        }), 500

@app.route('/api/admin/takedown', methods=['POST'])
def execute_takedown():
    """
    Administrative Takedown wiring for future Command Center button.
    Neutralizes a listing by adding its ID to the registry.
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    data = request.json
    listing_id = data.get('listingId')
    
    if not listing_id:
        return jsonify({"success": False, "error": "ID Required"}), 400

    try:
        db.collection('artifacts').document(APP_ID)\
          .collection('public').document('data')\
          .collection('takedown_registry').document(listing_id).set({
              "timestamp": firestore.SERVER_TIMESTAMP,
              "reason": data.get('reason', 'Institutional Safety Audit'),
              "active": True
          })
        return jsonify({"success": True, "message": f"Listing {listing_id} neutralized."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    
@app.route('/paystack/webhook', methods=['POST'])
def paystack_webhook():
    # ========================================================
    # 1. CRYPTOGRAPHIC SIGNATURE VALIDATION (ANTI-SPOOFING)
    # ========================================================
    paystack_signature = request.headers.get('x-paystack-signature')
    
    if not paystack_signature:
        print("🛡️ SECURITY ALERT: Missing Paystack signature header! Request dropped.")
        return "Unauthorized", 401

    # Compute expected signature using local secret key and incoming raw request bytes
    computed_signature = hmac.new(
        bytes(PAYSTACK_SECRET_KEY, 'utf-8'),
        request.data,  # Essential: Use raw bytes to preserve original serialization
        hashlib.sha512
    ).hexdigest()

    # Time-constant comparison protects the server from targeted timing analysis
    if not hmac.compare_digest(computed_signature, paystack_signature):
        print("🛡️ SECURITY ALERT: Invalid Webhook Signature! Verification handshake failed.")
        return "Unauthorized", 401

    # ========================================================
    # 2. SIGNATURE SECURED: SAFE TO UNPACK THE ENVELOPE
    # ========================================================
    data = request.json
    print(f"WEBHOOK RECEIVED: {data.get('event')}")

    if data['event'] == "charge.success":
        payload = data['data']
        meta = payload.get('metadata', {}).get('custom_fields', [])
        
        try:
            # 1. EXTRACT DATA
            listing_id = next((f['value'] for f in meta if f['variable_name'] == 'listing_id'), None)
            buyer_phone = next((f['value'] for f in meta if f['variable_name'] == 'phone'), "Unknown")
            device_token = next((f['value'] for f in meta if f['variable_name'] == 'device_token'), "None")
            item_name = next((f['value'] for f in meta if f['variable_name'] == 'item_name'), "Item")
            
            # --- NEW: Extract the buyer's custom Delivery PIN ---
            user_defined_pin = next((f['value'] for f in meta if f['variable_name'] == 'delivery_pin'), None)
            
            # --- THE BATON: Extract the Seller's Phone Number ---
            seller_momo = next((f['value'] for f in meta if f['variable_name'] == 'seller_phone'), None)
            
            if not listing_id:
                print("❌ WEBHOOK ERROR: No listing_id found in metadata.")
                return "Missing ID", 400

            # 2. SAVE TO FIRESTORE (Using Paystack Reference as Doc Name)
            order_id = payload['reference'] 
            order_ref = db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('orders').document(order_id)
            
            order_ref.set({
                "status": "paid_in_escrow",
                "listing_id": listing_id,
                "securityStamp": {
                    "token": device_token,
                    "ip": payload.get('ip_address'),
                    "handoffPin": user_defined_pin  # <--- Pin natively bound to the transaction
                },
                "item": item_name,
                "amount": payload['amount'] / 100,
                "buyerPhone": buyer_phone,
                "momo": seller_momo,  
                "paystack_ref": order_id, 
                "createdAt": firestore.SERVER_TIMESTAMP
            })
            
            print(f"✅ SECURED: Order {order_id} created. PIN saved. Merchant {seller_momo} linked.")

            # ========================================================
            # 3. SANITIZE & SEND DUAL SMS NOTIFICATIONS
            # ========================================================
            try:
                # --- Helper function to format numbers for Hubtel (054... -> 23354...) ---
                def format_gh_phone(raw_phone):
                    phone_str = str(raw_phone).strip()
                    if phone_str.startswith('0'):
                        return '233' + phone_str[1:]
                    elif not phone_str.startswith('233') and phone_str not in ["Unknown", "None"]:
                        return '233' + phone_str
                    return phone_str

                clean_buyer_phone = format_gh_phone(buyer_phone)
                clean_seller_phone = format_gh_phone(seller_momo)

                print(f"📱 SMS ROUTING LOG:")
                print(f"   Buyer: {clean_buyer_phone}")
                print(f"   Seller: {clean_seller_phone}")

                # --- SMS #1: TO THE BUYER ---
                if clean_buyer_phone != "Unknown":
                    buyer_msg = f"Payment for {item_name} secured! Call the seller at 0{clean_seller_phone[3:]} to confirm the meetup on campus. Scan their QR code only after you have the item in hand and have inspected it."
                    
                    # Capture the true status of the API call
                    buyer_sms_sent = send_professional_sms(clean_buyer_phone, buyer_msg)
                    
                    if buyer_sms_sent:
                        print("✅ Buyer SMS successfully accepted by Hubtel gateway.")
                    else:
                        print("❌ Buyer SMS failed to dispatch.")
                else:
                    print("⚠️ Buyer SMS skipped: Phone number is Unknown.")

                # --- SMS #2: TO THE MERCHANT ---
                if clean_seller_phone not in ["Unknown", "None"]:
                    merchant_msg = f"Great news! Your {item_name} has been paid for. Call the buyer at 0{clean_buyer_phone[3:]} to arrange the handover. Let them scan your QR code when you meet so you get your money."
                    
                    merchant_sms_sent = send_professional_sms(clean_seller_phone, merchant_msg)
                    
                    if merchant_sms_sent:
                        print("✅ Merchant SMS successfully accepted by Hubtel gateway.")
                    else:
                        print("❌ Merchant SMS failed to dispatch.")
                else:
                    print("⚠️ Merchant SMS skipped: Seller phone number is missing.")

            except Exception as sms_err:
                print(f"⚠️ Dual-SMS Pipeline failed: {str(sms_err)}")
            
        except Exception as e:
            print(f"❌ WEBHOOK PROCESSING ERROR: {str(e)}")

    return "OK", 200

@app.route('/api/gatekeeper/verify', methods=['POST'])
def gatekeeper_verify():
    data = request.json
    listing_id = data.get('listingId') 
    
    # Path A parameters (Seamless Token)
    current_stamp = data.get('securityStamp') or {}
    token = current_stamp.get('token') or data.get('token')

    # Path B parameters (Manual popup fallback)
    buyer_phone = data.get('buyerPhone')
    incoming_pin = data.get('handoffPin')

    # Guard clause: We only strictly require the listingId upfront
    if not listing_id:
        print("Verify Attempt Fail: Missing listingId")
        return jsonify({"success": False, "error": "Missing listing ID."}), 400

    try:
        # 1. Reference the orders collection
        orders_ref = db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('orders')
        docs = []

        # ========================================================
        # PATH A: Seamless Token Match
        # ========================================================
        if token:
            query = orders_ref.where(filter=FieldFilter('listing_id', '==', listing_id)) \
                              .where(filter=FieldFilter('status', 'in', ['paid_in_escrow', 'buyer_reviewing']))\
                              .where(filter=FieldFilter('securityStamp.token', '==', token)) \
                              .limit(1).get()
            docs = list(query)

        # ========================================================
        # PATH B: Manual Phone + PIN Bypass (Upgraded for Cryptographic Matching)
        # ========================================================
        if not docs and buyer_phone and incoming_pin:
            p = str(buyer_phone).strip()
            phone_variants = [p, '233' + p[1:] if p.startswith('0') else p, '0' + p[3:] if p.startswith('233') else p]
            
            raw_pin_string = str(incoming_pin).strip()
            hashed_pin_signature = hashlib.sha256(raw_pin_string.encode('utf-8')).hexdigest()
            
            query = orders_ref.where(filter=FieldFilter('listing_id', '==', listing_id)) \
                              .where(filter=FieldFilter('status', 'in', ['paid_in_escrow', 'buyer_reviewing']))\
                              .where(filter=FieldFilter('buyerPhone', 'in', phone_variants)) \
                              .where(filter=FieldFilter('securityStamp.handoffPin', '==', hashed_pin_signature)) \
                              .limit(1).get()
            docs = list(query)

        # 3. Check results
        if not docs:
            print(f"Verify Attempt Fail: No matching active escrow for Listing {listing_id}.")
            return jsonify({
                "success": False, 
                "error": "Authentication Failed"
            }), 404

        # 4. Extract data cleanly 
        target_doc = docs[0]
        order_data = target_doc.to_dict() 
        paystack_ref = target_doc.id 
        order_ref = target_doc.reference
        item_name = order_data.get('item', 'Item')

        # ========================================================
        # ANTI-HACKING CIRCUIT BREAKER (MAX 5 ATTEMPTS)
        # ========================================================
        failed_attempts = order_data.get('failed_attempts', 0)
        
        if failed_attempts >= 5:
            print(f"🛡️ BRUTE-FORCE BLOCKED: Listing {listing_id} locked down due to {failed_attempts} failed attempts.")
            return jsonify({
                "success": False, 
                "error": "Authentication Failed"
            }), 404

        # ========================================================
        # MANUAL VALIDATION
        # ========================================================
        actual_token = order_data.get('securityStamp', {}).get('token')
        actual_pin_hash = order_data.get('securityStamp', {}).get('handoffPin')
        
        is_valid = False
        if token and actual_token == token:
            is_valid = True
        elif incoming_pin:
            calculated_hash = hashlib.sha256(str(incoming_pin).strip().encode('utf-8')).hexdigest()
            if actual_pin_hash == calculated_hash:
                is_valid = True
            
        if not is_valid:
            new_failures = failed_attempts + 1
            order_ref.update({"failed_attempts": new_failures})
            print(f"⚠️ SECURITY: Invalid token/PIN attempt for Listing {listing_id}. Total failures: {new_failures}/5")
            return jsonify({
                "success": False, 
                "error": "Authentication Failed"
            }), 404

        # ========================================================
        # 5. CRITICAL: Update Database State FIRST (Credentials Validated)
        # ========================================================
        order_ref.update({
            "status": "completed",
            "failed_attempts": 0  # Clear counter on genuine completion
        })
        print(f"✅ HANDSHAKE SUCCESSFUL: Order {paystack_ref} locked and marked completed.")
        
        # ========================================================
        # 💸 NEW: INTEGRATED AUTOMATED PAYSTACK TRANSFER PIPELINE
        # ========================================================
        raw_merchant_phone = order_data.get('momo') or order_data.get('merchantPhone')
        merchant_id_string = order_data.get('merchantId', 'Verified Merchant')
        gross_price_raw = order_data.get('amount', 0.0)

        if raw_merchant_phone and gross_price_raw:
            try:
                # Execution Math Split: Gross minus 5% commission, minus GHS 0.40 user share of MoMo cost
                gross_amount = float(gross_price_raw)
                ledgehold_commission = gross_amount * 0.05
                net_subtotal = gross_amount - ledgehold_commission
                final_payout_volume = net_subtotal - 0.40
                
                if final_payout_volume > 0:
                    payout_kobo_integer = int(round(final_payout_volume * 100))
                    paystack_headers = {
                        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                        "Content-Type": "application/json"
                    }

                    # 1. NETWORK PREFIX DETECTION
                    momo_str = str(raw_merchant_phone).strip()
                    # Normalize to local format (0xxxxxxxxx) for prefix matching
                    if momo_str.startswith('233'): momo_str = '0' + momo_str[3:]
                    
                    # Determine Bank Code for Paystack
                    bank_code = 'MTN' # Default
                    if momo_str.startswith(('024', '054', '055', '059', '025')):
                        bank_code = 'MTN'
                    elif momo_str.startswith(('020', '050')):
                        bank_code = 'TCL'
                    elif momo_str.startswith(('027', '057', '026', '056')):
                        bank_code = 'ATL'

                    # 2. UPDATED RECIPIENT DATA (Use this to replace your old recipient_data block)
                    recipient_data = {
                        "type": "mobile_money", 
                        "name": merchant_id_string,
                        "account_number": str(raw_merchant_phone).strip(),
                        "bank_code": bank_code, # <--- The missing link
                        "currency": "GHS"
                    }

                    rcp_req = requests.post("https://api.paystack.co/transferrecipient", json=recipient_data, headers=paystack_headers).json()
                    
                    if rcp_req.get('status'):
                        recipient_code = rcp_req['data']['recipient_code']

                        # Step B: Discharge Outbound Balance to MoMo Target
                        transfer_data = {
                            "source": "balance",
                            "amount": payout_kobo_integer,
                            "recipient": recipient_code,
                            "reason": f"Ledgehold Escrow Release. Ref: {paystack_ref}",
                            "reference": str(uuid.uuid4()) # Idempotency Block
                        }
                        payout_req = requests.post("https://api.paystack.co/transfer", json=transfer_data, headers=paystack_headers).json()
                        
                        if payout_req.get('status'):
                            print(f"💸 PIPELINE SUCCESS: GHS {final_payout_volume:.2f} automated transfer fired to {merchant_id_string}.")
                        else:
                            print(f"🚨 PAYSTACK API PAYOUT REJECTION: {payout_req.get('message')}")
                    else:
                        print(f"🚨 PAYSTACK RECIPIENT NODE REGISTRY REJECTION: {rcp_req.get('message')}")
                else:
                    print(f"⚠️ PIPELINE ABORTED: Volume balance GHS {final_payout_volume:.2f} too low to calculate.")
            except Exception as payout_err:
                print(f"🚨 CRITICAL SYSTEM CRASH INSIDE PAYSTACK TRANSFER ENGINE: {str(payout_err)}")
        else:
            print("⚠️ PAYOUT SKIPPED: Missing crucial MoMo target details or price anchors inside order document.")

        # ========================================================
        # 6. TRIGGER NOTIFICATIONS (Non-blocking)
        # ========================================================
        
        def format_gh_phone(raw_phone):
            phone_str = str(raw_phone).strip() if raw_phone else ""
            if not phone_str or phone_str in ["Unknown", "None"]:
                return "Unknown"
            if phone_str.startswith('0'):
                return '233' + phone_str[1:]
            elif not phone_str.startswith('233'):
                return '233' + phone_str
            return phone_str

        raw_buyer_phone = order_data.get('buyerPhone')
        clean_buyer_phone = format_gh_phone(raw_buyer_phone)
        clean_merchant_phone = format_gh_phone(raw_merchant_phone)

        # A. Dual Hubtel SMS Notifications
        try:
            # --- SMS #1: TO THE MERCHANT ---
            if clean_merchant_phone != "Unknown":
                merchant_success_msg = f"Handover complete! Your payment for {item_name} is being processed and will be sent to your MoMo wallet shortly. Thank you for working with Ledgehold."
                send_professional_sms(clean_merchant_phone, merchant_success_msg)
                print(f"✅ Handover success SMS dispatched to Merchant: {clean_merchant_phone}")
            else:
                print("⚠️ Merchant SMS Skipped: No merchant phone details found in document.")

            # --- SMS #2: TO THE BUYER ---
            if clean_buyer_phone != "Unknown":
                buyer_success_msg = f"Handover confirmed! Your payment has been safely delivered to the seller. Thank you for choosing Ledgehold."
                send_professional_sms(clean_buyer_phone, buyer_success_msg)
                print(f"✅ Handover success SMS dispatched to Buyer: {clean_buyer_phone}")
            else:
                print("⚠️ Buyer SMS Skipped: No buyer phone details found in document.")

        except Exception as sms_err:
            print(f"⚠️ Dual-SMS Notification Segment Failed: {str(sms_err)}")

        # B. Resend Email Audit
        try:
            send_handoff_email(order_data, paystack_ref)
        except Exception as email_err:
            print(f"⚠️ Resend Audit Failed: {str(email_err)}")

        return jsonify({"success": True, "verified": True})

    except Exception as e:
        print(f"System Error: {str(e)}")
        return jsonify({"success": False, "error": "Internal System Error"}), 500
    
@app.route('/verify_order')
def verify_order_landing():
    # This renders the page the buyer scans into
    return render_template('buyer_verify.html', **get_firebase_context())

@app.route('/api/gatekeeper/review', methods=['POST'])
def gatekeeper_set_review():
    data = request.json
    listing_id = data.get('listingId')
    
    # Path A parameters
    token = data.get('token') 
    
    # Path B parameters (Manual popup fallback)
    buyer_phone = data.get('buyerPhone')
    handoff_pin = data.get('handoffPin')
    
    # Guard clause: We only strictly require the listingId upfront. 
    if not listing_id:
        print("Review Attempt Fail: Missing listingId")
        return jsonify({"success": False, "error": "Missing listing ID."}), 400
        
    try:
        orders_ref = db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('orders')
        docs = []

        # ========================================================
        # PATH A: Seamless Token Match
        # ========================================================
        if token:
            query = orders_ref.where(filter=FieldFilter('listing_id', '==', listing_id))\
                              .where(filter=FieldFilter('status', '==', 'paid_in_escrow'))\
                              .where(filter=FieldFilter('securityStamp.token', '==', token))\
                              .limit(1).get()
            docs = list(query)

        # ========================================================
        # PATH B: Manual Phone + PIN Bypass (Upgraded for Cryptographic Matching)
        # ========================================================
        if not docs and buyer_phone and handoff_pin:
            print(f"🔄 Identity Bypass: Attempting manual verification for Phone: {buyer_phone}")
            
            # Format phone to handle '054...' vs '23354...' safely
            p = str(buyer_phone).strip()
            phone_variants = [p, '233' + p[1:] if p.startswith('0') else p, '0' + p[3:] if p.startswith('233') else p]
            
            # CRITICAL SECURITY MATCH: Hash the manual plain text string to challenge the signature in DB
            raw_pin_string = str(handoff_pin).strip()
            hashed_pin_signature = hashlib.sha256(raw_pin_string.encode('utf-8')).hexdigest()
            
            query = orders_ref.where(filter=FieldFilter('listing_id', '==', listing_id))\
                              .where(filter=FieldFilter('status', '==', 'paid_in_escrow'))\
                              .where(filter=FieldFilter('buyerPhone', 'in', phone_variants))\
                              .where(filter=FieldFilter('securityStamp.handoffPin', '==', hashed_pin_signature))\
                              .limit(1).get()
            docs = list(query)

        # Final Identity Gate
        if not docs:
            print(f"Review Sync Fail: No active escrow found for Listing {listing_id} with provided credentials.")
            return jsonify({"success": False, "error": "Authentication Failed"}), 404
            
        target_doc = docs[0]
        
        # Advance the order state to flip the merchant's UI screen to blue
        target_doc.reference.update({"status": "buyer_reviewing"})
        print(f"🔒 STATE UPDATE: Order {target_doc.id} shifted to buyer_reviewing state.")
        
        return jsonify({"success": True}), 200
        
    except Exception as e:
        print(f"🛡️ Security Pipeline Exception inside Review Route: {str(e)}")
        return jsonify({"success": False, "error": "Internal Processing Error"}), 500

@app.route('/foodrun')
def food_run_page():
    # Logic: Open Friday (4), Saturday (5), Sunday (6)
    today_idx = datetime.datetime.now().weekday()
    today_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][today_idx]
    
    if today_idx >= 4:
        state = "open"
        # The Menu is now indented inside the IF block
        menu = [
            {
                "item": "KFC Streetwise 2 (Rice)", 
                "price": 90.00, 
                "img": "https://cdn.tictuk.com/staging/fc9ab8a5-b3d3-4cf6-0e30-555e691086bf/7824c8df-6c6b-d80d-7e44-877899c2ed9b.jpeg?a=d1cb9c76-1f98-19c4-1a27-597c125b2738",
                "description": "Classic KFC chicken with seasoned rice and signature sauce",
                "prep_time": "25"
            },
            {
                "item": "Waakye Special (Egg + Fish)", 
                "price": 30.00, 
                "img": "https://tse2.mm.bing.net/th/id/OIP.u3ot8N9zmflWBBd4S4Lq-QHaJL?cb=ucfimg2&ucfimg=1&rs=1&pid=ImgDetMain&o=7&rm=3",
                "description": "Traditional Ghanaian waakye with boiled egg and fried fish",
                "prep_time": "20"
            },
            {
                "item": "Pizza (Medium Size)", 
                "price": 120.00, 
                "img": "https://images.unsplash.com/photo-1513104890138-7c749659a591?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=80",
                "description": "Mid-sized pizza with suprise toppings",
                "prep_time": "5"
            },
            {
                "item": "Jollof Rice + Chicken", 
                "price": 45.00, 
                "img": "https://th.bing.com/th/id/OIP.n_wJL9qZ16lh_uiRCqNiUgHaHa?w=197&h=197&c=7&r=0&o=7&cb=ucfimg2&dpr=1.5&pid=1.7&rm=3&ucfimg=1",
                "description": "Spicy Ghanaian jollof rice with grilled chicken",
                "prep_time": "25"
            },
            {
                "item": "Fried Rice + Chicken", 
                "price": 45.00, 
                "img": "https://th.bing.com/th/id/OIP.RfVI9SuTBNY6oWetN8uMXgHaFO?w=252&h=180&c=7&r=0&o=7&cb=ucfimg2&dpr=1.5&pid=1.7&rm=3&ucfimg=1",
                "description": "Fried rice with vegetables and grilled chicken",
                "prep_time": "25"
            },
            {
                "item": "Banku + Tilapia", 
                "price": 40.00, 
                "img": "https://th.bing.com/th/id/OIP.6rFklsZZtFe5ylXkNsz1hgHaHa?w=173&h=180&c=7&r=0&o=7&cb=ucfimg2&dpr=1.5&pid=1.7&rm=3&ucfimg=1",
                "description": "Fresh tilapia with banku and pepper sauce",
                "prep_time": "30"
            },
            {
                "item": "Plain Rice + Chicken Stew", 
                "price": 35.00, 
                "img": "https://th.bing.com/th/id/OIP.kBNJKGnK8BFTISvoUVRlIwHaFI?w=251&h=180&c=7&r=0&o=7&cb=ucfimg2&dpr=1.5&pid=1.7&rm=3&ucfimg=1",
                "description": "Steamed rice with rich chicken stew",
                "prep_time": "20"
            }
        ]
        random.shuffle(menu)
    else:
        # The ELSE is now aligned correctly with the IF
        state = "closed"
        menu = []

    return render_template('foodrun.html', state=state, menu=menu, today_name=today_name, today_idx=today_idx)

#@app.route('/quote')
#def quote_page():
    #return render_template('quote.html')

@app.route('/marketing_toolkit')
def marketing():
    cloudinary_name = os.getenv('CLOUDINARY_CLOUD_NAME')
    return render_template('marketing_toolkit.html',CLOUDINARY_CLOUD_NAME=cloudinary_name, **get_firebase_context())

@app.route('/endorsement')
def endorsement():
    return render_template('endorsement.html', **get_firebase_context())

@app.route('/marketplace')
def marketplace():
    return render_template('marketplace.html', **get_firebase_context())

@app.route('/inventory_management')
def inventory():
    actual_key = os.getenv('IMGBB_API_KEY')
    return render_template('inventory_management.html', **get_firebase_context())

@app.route('/seller_onboarding')
@app.route('/onboarding') # Both URLs now lead here and pass the key
def onboarding():
    return render_template('seller_onboarding.html', **get_firebase_context())

@app.route('/list_item')
def list_item():
    return render_template('list_item.html', **get_firebase_context())

@app.route('/directory')
def directory():
    return render_template('directory.html')

@app.route('/faq')
def faq():
    return render_template('faq.html')

@app.route('/handshake')
def handshake():
    return render_template('handshake.html', **get_firebase_context())

@app.route('/cms')
def admin():
    # We must pass the Firebase context so the Canvas can initialize the DPA Registry
    return render_template('cms.html', **get_firebase_context())

@app.route('/merchant_dashboard')
def merchant_dashboard():
    # We must pass the Firebase context so the Canvas can initialize the DPA Registry
    return render_template('merchant_dashboard.html', **get_firebase_context())

@app.route('/shop')
def shop():
    return render_template('shop.html')

@app.route('/receipt_generator')
def receipt_generator():
    return render_template('receipt_generator.html', **get_firebase_context())

@app.route('/intel')
def intel():
    return render_template('insights.html', **get_firebase_context())

@app.route('/merch')
def merch():
    return render_template('merch.html', **get_firebase_context())

@app.route('/checkout')
def checkout():
    pub_key = os.getenv("PAYSTACK_PUBLIC_KEY")
    return render_template('checkout.html', paystack_pub_key=pub_key, **get_firebase_context())

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/merchant_guide')
def guide():
    return render_template('merchant_guide.html')

@app.route('/success')
def success_page():
    return render_template('success.html')

@app.route('/about_us')
def about():
    return render_template('about_us.html')

@app.route('/terms')
def terms_page():
    return render_template('terms.html')

# --- TV / ENTERTAINMENT (HIDDEN IN COMPLIANCE MODE) ---
@app.route('/tv')
def tv_page():
    if COMPLIANCE_MODE:
        return render_template('maintenance.html', page_name="Entertainment Hub")

    # A. THE MOVIE POOL (From second code - complete list)
    movies = [
        {"id": "43R9l7EkJwE", "title": "Predator: Badlands", "creator": "20th Century", "type": "video"},
        {"id": "OpThntO9ixc", "title": "Weapons", "creator": "Warner Bros", "type": "video"},
        {"id": "8yh9BPUBbbQ", "title": "F1® The Movie", "creator": "Warner Bros", "type": "video"},
        {"id": "-E3lMRx7HRQ", "title": "Now You See Me 3", "creator": "Lionsgate", "type": "video"},
        {"id": "DCWcK4c-F8Q", "title": "The Amateur", "creator": "20th Century", "type": "video"},
        {"id": "vEioDeOiqEs", "title": "Murderbot", "creator": "Apple TV", "type": "video"},
        {"id": "bMgfsdYoEEo", "title": "The Conjuring: Last Rites", "creator": "Warner Bros", "type": "video"},
        {"id": "dqolYtJGuf4", "title": "The Family Plan 2", "creator": "Apple TV", "type": "video"},
        {"id": "AuYmKbtnmEA", "title": "Michael", "creator": "Universal", "type": "video"},
        {"id": "5r-7eWDBc40", "title": "GOAT", "creator": "Sony Pictures", "type": "video"},
        {"id": "tA1s65o_kYM", "title": "Mickey 17", "creator": "Warner Bros", "type": "video"},
        {"id": "lMXh6vjiZrI", "title": "Mufasa: The Lion King", "creator": "Disney", "type": "video"},
        {"id": "1pHDWnXmK7Y", "title": "Captain America 4", "creator": "Marvel", "type": "video"},
        {"id": "lQBmZBJCYcY", "title": "Squid Game Season 2", "creator": "Netflix", "type": "video"},
        {"id": "dSDpoobO6yM", "title": "Five Nights at Freddy's 2", "creator": "Universal", "type": "video"},
        {"id": "az8M5Mai0X4", "title": "Anaconda", "creator": "Sony Pictures", "type": "video"},
        {"id": "EOwTdTZA8D8", "title": "28 Years Later", "creator": "Sony Pictures", "type": "video"},
        {"id": "n0pqP6ClcE8", "title": "Rental Family", "creator": "Searchlight", "type": "video"},
        {"id": "R4wiXj9NmEE", "title": "Send Help", "creator": "20th Century", "type": "video"},
        {"id": "zHhR3daI3bY", "title": "Man Vs Baby", "creator": "Netflix", "type": "video"},
        {"id": "m3lgD59KrTw", "title": "Hedda", "creator": "Prime Video", "type": "video"},
        {"id": "Hzk4ovnGOyw", "title": "Troll 2", "creator": "Netflix", "type": "video"},
        {"id": "8seUGDLZRIo", "title": "Swiped", "creator": "Hulu", "type": "video"},
        {"id": "vAtUHeMQ1F8", "title": "The Long Walk", "creator": "Lionsgate Movies", "type": "video"},
        {"id": "M7LhGytiHFM", "title": "Shadow Force", "creator": "Lionsgate Movies", "type": "video"},
        {"id": "o34WOE1a8aQ", "title": "Good Fortune", "creator": "Lionsgate Movies", "type": "video"},
        {"id": "moiRCJR4ToY", "title": "The Blackening", "creator": "Lionsgate Movies", "type": "video"},
        {"id": "H8ieN10lX40", "title": "Greenland 2", "creator": "Lionsgate Movies", "type": "video"},
        {"id": "U9OkHjOnQPg", "title": "She Rides Shotgun", "creator": "Lionsgate Movies", "type": "video"},
        {"id": "k_8YOQ0TMfM", "title": "Turbulence", "creator": "Lionsgate Movies", "type": "video"},
        {"id": "_wpw2QHJNco", "title": "A House Of Dynamite", "creator": "Netflix", "type": "video"},
        {"id": "MPjxijuBuSo", "title": "The Hunger Games: Sunrise on the Reaping", "creator": "Lionsgate Movies", "type": "video"},
        {"id": "f5y-cziwmMw", "title": "Crime 101", "creator": "Amazon MGM Studios", "type": "video"},
        {"id": "KD18ddeFuyM", "title": "The Running Man", "creator": "Paramount Pictures", "type": "video"},
        {"id": "i36Zw32GfRQ", "title": "Reminders of Him", "creator": "Universal Pictures", "type": "video"},
        {"id": "kr3wIXhmYpI", "title": "Strays", "creator": "Universal Pictures", "type": "video"},
        {"id": "YShVEXb7-ic", "title": "Tron: Ares", "creator": "Disney", "type": "video"},
        {"id": "IHikM7vFXsA", "title": "Roofman", "creator": "Paramount Pictures", "type": "video"},
        {"id": "ZsAa9ofaL-g", "title": "Red Alert", "creator": "Paramount Plus", "type": "video"},
        {"id": "z1xJAyVKAPY", "title": "The Black Demon", "creator": "Paramount Movies", "type": "video"},
        {"id": "nfKO9rYDmE8", "title": "The Lost City", "creator": "Paramount Pictures", "type": "video"},
        {"id": "R6W6YzhRuTA", "title": "SHELL", "creator": "Paramount Movies", "type": "video"}
    ]

    random.shuffle(movies)

    # ADS - Only add Stake ads when NOT in compliance mode
    #if not COMPLIANCE_MODE:
        #ad_1 = {
            #"type": "ad",
            #"title": "Win like Drake with Stake",
            #"desc": "Instant Withdrawals via MoMo or Crypto. 200% Bonus.",
            #"link": "https://stake.com/?c=TqdL9FFw",
            #"image": "/static/images/stake-logo-navy.png"
        #}
        
        #ad_2 = {
            #"type": "ad",
            #"title": "Sign up today, it may be your lucky day",
            #"desc": "The world's biggest crypto casino. Play now.",
            #"link": "https://stake.com/?c=TqdL9FFw",
            #"image": "/static/images/stake com-logo-navy.png"
        #}

        #ad_3 = {
            #"type": "ad",
            #"title": "Stake and Win",
            #"desc": "Join the winning team. 200% Deposit Match.",
            #"link": "https://stake.com/?c=TqdL9FFw",
            #"image": "/static/images/stake-logo-navy.png"
        #}

        # INJECT ADS AT FIXED POSITIONS (From second code)
        # Insert from last to first to avoid messing up the index order
        #if len(movies) > 41: movies.insert(41, ad_3)
        #if len(movies) > 32: movies.insert(32, ad_2)
        #if len(movies) > 25: movies.insert(25, ad_1)
        #if len(movies) > 16: movies.insert(16, ad_3)
        #if len(movies) > 8: movies.insert(8, ad_2)
        #if len(movies) > 3: movies.insert(3, ad_1)
    
    return render_template('tv.html', videos=movies)


# --- UNIVERSAL BUY PAGE ---
@app.route('/buy/<network>')
def product_page(network):

    # MASTER PRICE LIST
    pricing = {
        # --- DATA BUNDLES (Keep these active for 'Campus Connectivity') ---
        "mtn": [
            {"name": "1GB Non-Expiry", "price": 14, "input_type": "phone", "active": True}, 
            {"name": "2GB Non-Expiry", "price": 29, "input_type": "phone", "active": True},
            {"name": "3GB Non-Expiry", "price": 43, "input_type": "phone", "active": True},
            {"name": "4GB Non-Expiry", "price": 58, "input_type": "phone", "active": True},
            {"name": "5GB Non-Expiry", "price": 73, "input_type": "phone", "active": True },
            {"name": "6GB Non-Expiry", "price": 88, "input_type": "phone", "active": True},
            {"name": "9GB Non-Expiry", "price": 100, "input_type": "phone", "active": True},
            {"name": "10GB Non-Expiry", "price": 110, "input_type": "phone", "active": True},
            {"name": "15GB Non-Expiry", "price": 166, "input_type": "phone", "active": True},
            {"name": "30GB Non-Expiry", "price": 200, "input_type": "phone", "active": True},
            {"name": "40GB Non-Expiry", "price": 260, "input_type": "phone", "active": True},
            {"name": "45GB Non-Expiry", "price": 295, "input_type": "phone", "active": True},
            {"name": "100GB Non-Expiry", "price": 328, "input_type": "phone", "active": True},
        ],
        "telecel": [
            {"name": "10GB Special", "price": 100, "input_type": "phone", "active": True},
            {"name": "15GB Special", "price": 140, "input_type": "phone", "active": True},
            {"name": "20GB Non-Expiry", "price": 150, "input_type": "phone", "active": True},
            {"name": "25GB Non-Expiry", "price": 162, "input_type": "phone", "active": True},
            {"name": "30GB Non-Expiry", "price": 180, "input_type": "phone", "active": True},
            {"name": "40GB Non-Expiry", "price": 240, "input_type": "phone", "active": True},
            {"name": "50GB Non-Expiry", "price": 270, "input_type": "phone", "active": True},
            {"name": "100GB Non-Expiry", "price": 300, "input_type": "phone", "active": True},
        ],
        "at": [
            {"name": "1GB Non-Expiry", "price": 10, "input_type": "phone", "active": True},
            {"name": "3GB Non-Expiry", "price": 34, "input_type": "phone", "active": True},
            {"name": "4GB Non-Expiry", "price": 48, "input_type": "phone", "active": True},
            {"name": "5GB Non-Expiry", "price": 53, "input_type": "phone", "active": True},
            {"name": "8GB Non-Expiry", "price": 75, "input_type": "phone", "active": True},
            {"name": "10GB Non-Expiry", "price": 95, "input_type": "phone", "active": True},
            {"name": "12GB Non-Expiry", "price": 113, "input_type": "phone", "active": True},
        ]
    }
    
    selected_bundles = pricing.get(network, [])
    data_networks = ['mtn', 'telecel', 'at']
    is_voucher = network not in data_networks
    
    # Fallback to 'phone' if empty
    input_type = selected_bundles[0]['input_type'] if selected_bundles else 'phone'
    
    return render_template('product.html', 
                           network_name=network.upper(), 
                           bundles=selected_bundles,
                           input_type=input_type,
                           is_voucher=is_voucher)

# --- PAYMENT VERIFICATION ---
@app.route('/verify_payment', methods=['POST'])
def verify_payment():
    data = request.json
    reference = data.get('reference')
    
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    
    try:
        response = requests.get(url, headers=headers)
        json_resp = response.json()
        
        if json_resp['status'] is True and json_resp['data']['status'] == "success":
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "failed"})
            
    except Exception as e:
        print(f"Error connecting to Paystack: {e}")
        return jsonify({"status": "error"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))