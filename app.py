from flask import Flask, render_template, request, jsonify, redirect
import requests
import os
import random
import datetime
import resend
import firebase_admin
import requests
from base64 import b64encode
from firebase_admin import credentials, firestore, initialize_app
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

resend.api_key = os.getenv("RESEND_API_KEY")

app = Flask(__name__)

# Hubtel SMS Auth
HUB_ID = os.getenv('HUBTEL_CLIENT_ID')
HUB_SECRET = os.getenv('HUBTEL_CLIENT_SECRET')
HUB_AUTH = b64encode(f"{HUB_ID}:{HUB_SECRET}".encode()).decode()


# --- SECURE TEST CREDENTIALS & CONFIGURATION 
PAYSTACK_SECRET_KEY = "sk_test_205609e95584b8704c90e2c8c72b6f1dbcee60db"

# Admin Access
ADMIN_ID = os.environ.get("ADMIN_ID")
ADMIN_PIN = os.environ.get("ADMIN_PIN")

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
            "from": "Handoff Alerts <onboarding@resend.dev>", # Use your verified Resend domain
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
                    "ip": payload.get('ip_address') 
                },
                "item": item_name,
                "amount": payload['amount'] / 100,
                "buyerPhone": buyer_phone,
                "momo": seller_momo,  # <--- Storing the seller's number as 'momo'
                "paystack_ref": order_id, 
                "createdAt": firestore.SERVER_TIMESTAMP
            })
            
            print(f"✅ SECURED: Order {order_id} created. Merchant {seller_momo} linked.")

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
                    buyer_msg = f"Ledgehold: Payment for {item_name} secured! Call the seller at 0{clean_seller_phone[3:]} to confirm the meetup on campus. Scan their QR code only after you have the item in hand and have inspected it."
                    
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
    current_stamp = data.get('securityStamp') or {}
    token = current_stamp.get('token')

    # Guard clause: Fail fast if vital verification parameters are missing
    if not listing_id or not token:
        print("Verify Attempt Fail: Missing listingId or security token")
        return jsonify({"success": False, "error": "Missing listing ID or device token."}), 400

    try:
        # 1. Reference the orders collection
        orders_ref = db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('orders')

        # 2. Query for the specific escrow record (Strict Token Match Only)
        query = orders_ref.where('listing_id', '==', listing_id) \
                          .where('status', '==', 'paid_in_escrow') \
                          .where('securityStamp.token', '==', token) \
                          .limit(1).get()

        # 3. Check results (IP Fallback has been removed entirely to secure campus Wi-Fi use)
        if not query:
            print(f"Verify Attempt Fail: No matching active escrow for Listing {listing_id} with this token.")
            return jsonify({
                "success": False, 
                "error": "Authentication Failed"
            }), 404

        # 4. Extract data
        target_doc = query
        order_data = target_doc.to_dict()
        paystack_ref = target_doc.id # The unique ID used for the audit email
        order_ref = target_doc.reference
        item_name = order_data.get('item', 'Item')

        # 5. CRITICAL: Update Database State FIRST
        order_ref.update({"status": "completed"})
        print(f"✅ HANDSHAKE SUCCESSFUL: Order {paystack_ref} locked and marked completed.")
        
        # 6. TRIGGER NOTIFICATIONS (Non-blocking)
        
        # Internal helper to clean and format strings for Hubtel (054... -> 23354...)
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
        raw_merchant_phone = order_data.get('momo') or order_data.get('merchantPhone')

        clean_buyer_phone = format_gh_phone(raw_buyer_phone)
        clean_merchant_phone = format_gh_phone(raw_merchant_phone)

        # A. Dual Hubtel SMS Notifications
        try:
            # --- SMS #1: TO THE MERCHANT ---
            if clean_merchant_phone != "Unknown":
                merchant_success_msg = f"Handover complete! Your payment for {item_name} is being processed and will be sent to your MoMo wallet shortly. Thank you for working with Ledgehold!"
                send_professional_sms(clean_merchant_phone, merchant_success_msg)
                print(f"✅ Handover success SMS dispatched to Merchant: {clean_merchant_phone}")
            else:
                print("⚠️ Merchant SMS Skipped: No merchant phone details found in document.")

            # --- SMS #2: TO THE BUYER ---
            if clean_buyer_phone != "Unknown":
                buyer_success_msg = f"Handover confirmed! Your payment has been safely delivered to the seller. Thank you for choosing Ledgehold"
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
    actual_key = os.getenv('IMGBB_API_KEY')
    return render_template('marketplace.html', **get_firebase_context())

@app.route('/inventory_management')
def inventory():
    actual_key = os.getenv('IMGBB_API_KEY')
    return render_template('inventory_management.html', **get_firebase_context())

@app.route('/seller_onboarding')
@app.route('/onboarding') # Both URLs now lead here and pass the key
def onboarding():
    # Fetch the key from the server environment
    # Note: Make sure you have set this in your terminal or .env file!
    actual_key = os.getenv('IMGBB_API_KEY') 
    
    # Pass it to the template
    return render_template('seller_onboarding.html', **get_firebase_context())

@app.route('/list_item')
def list_item():
    actual_key = os.getenv('IMGBB_API_KEY')
    return render_template('list_item.html', **get_firebase_context())

@app.route('/directory')
def directory():
    return render_template('directory.html')

@app.route('/faq')
def faq():
    return render_template('faq.html')

@app.route('/tracking')
def waybill():
    return render_template('waybill.html', **get_firebase_context())

@app.route('/handshake')
def handshake():
    return render_template('handshake.html', **get_firebase_context())

@app.route('/way_admin')
def way_admin():
    return render_template('way_admin.html', **get_firebase_context())

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/cms')
def admin():
    # We must pass the Firebase context so the Canvas can initialize the DPA Registry
    return render_template('cms.html', **get_firebase_context())

@app.route('/merchant_dashboard')
def merchant_dashboard():
    # We must pass the Firebase context so the Canvas can initialize the DPA Registry
    return render_template('merchant_dashboard.html', **get_firebase_context())

@app.route('/payout_portal')
def payout():
    actual_key = os.getenv('IMGBB_API_KEY') 
    # Pass it to the template
    return render_template('payout_portal.html', **get_firebase_context())

@app.route('/shop')
def shop():
    return render_template('shop.html')

#@app.route('/chat')
#def chat():
    #return render_template('chat.html', **get_firebase_context())

@app.route('/receipt_request')
def receipt():
    return render_template('receipt_request.html', **get_firebase_context())

@app.route('/receipt_generator')
def receipt_generator():
    return render_template('receipt_generator.html', **get_firebase_context())

#@app.route('/inbox')
#def inbox():
    #return render_template('inbox.html', **get_firebase_context())

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

# --- VOUCHERS (HIDDEN IN COMPLIANCE MODE) ---
#@app.route('/vouchers')
#def voucher_page():
    #if COMPLIANCE_MODE:
        #return render_template('maintenance.html', page_name="Voucher Mall")

    # From second code - complete voucher list
    items = [
        {
            "name": "Audiomack",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiJlOTVlM2NjOC0zNWYwLTQ5MjctOWM3MS0yMTRlN2ZiYzVmOTgucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjc2OH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "audiomack",
            "desc": "Subscription"
        },
        {
            "name": "Tinder",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiI5ZGQxOGRhYy0wN2E4LTQ3NTctYTQ5NC04YzU5MmNjYjE5M2UucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjM4NH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "tinder",
            "desc": "Subscription"
        },
        {
            "name": "EA Sports FC™ Mobile",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiIyNWNlMjI5Yi00YmQ3LTRjMTktOGE4Yy0zOTY5MzNiMmE5NDMucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjc2OH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "fcmobile",
            "desc": "FC Points"
        },
        {
            "name": "Free Fire",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiIwNDUzOTRmOC0zMWY1LTRlMDMtYjQ1OS03ZWEzMmJlZWY1YjQucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjM4NH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "freefire",
            "desc": "Diamonds"
        },
        {
            "name": "Call of Duty: Mobile",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiI4NmYyM2EwNi00MjI4LTQyNzctOTQwMS00ZWVlZTBkY2NmMzgucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjc2OH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "codm",
            "desc": "COD Points"
        },
        {
            "name": "EA Sports FC™ Mobile",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiIyNWNlMjI5Yi00YmQ3LTRjMTktOGE4Yy0zOTY5MzNiMmE5NDMucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjM4NH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "fcmobile.",
            "desc": "Silver"
        },
        {
            "name": "Call of Duty: Mobile",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiI4NmYyM2EwNi00MjI4LTQyNzctOTQwMS00ZWVlZTBkY2NmMzgucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjM4NH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "codm.",
            "desc": "Battle Pass"
        },
        {
            "name": "Marvel Rivals",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiIxMDRlYjFmNi1kMThiLTRjNGItODU4OS1iMWJiYjRiMzc4NzQucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpZml4Ing=",
            "link": "marvelrivals",
            "desc": "Lattices"
        },
        {
            "name": "Delta Force",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiIyYTVjYzFiYy00Yjg4LTQ2ZmYtYmFiZi04MTc3M2NkYTA1YTIucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjM4NH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "deltaforce",
            "desc": "Coins"
        },
        {
            "name": "Honor of Kings",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiIzZmJhZTU0Mi1iZTM0LTRjM2EtYmM1Yy0xYTE4NzYxOGU0NzMucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjM4NH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "honorofkings",
            "desc": "Tokens"
        },
        {
            "name": "Arena Breakout",
            "image": "https://d13ms5efar3wc5.cloudfront.net/eyJidWNrZXQiOiJpbWFnZXMtY2Fycnkxc3QtcHJvZHVjdHMiLCJrZXkiOiJmZTY2NTRjYy00YzEyLTQ5NWEtOGMzMi1kNjhiNDMwOTkwYjgucG5nLndlYnAiLCJlZGl0cyI6eyJyZXNpemUiOnsid2lkdGgiOjM4NH19LCJ3ZWJwIjp7InF1YWxpdHkiOjc1fX0=",
            "link": "arenabreakout",
            "desc": "Bonds"
        }
    ]
    return render_template('vouchers.html', items=items)

# --- UNIVERSAL BUY PAGE ---
@app.route('/buy/<network>')
def product_page(network):
    # If in Compliance Mode, BLOCK voucher networks
    risky_networks = ['audiomack', 'tinder', 'fcmobile', 'freefire', 'codm', 'marvelrivals', 'deltaforce', 'honorofkings', 'arenabreakout', 'fcmobile.', 'codm.']
    
    if COMPLIANCE_MODE and network in risky_networks:
        return render_template('maintenance.html', page_name="Digital Vouchers")

    # MASTER PRICE LIST (From second code - complete pricing)
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
        ],

        # --- VOUCHERS (These are blocked in COMPLIANCE_MODE) ---
        "audiomack": [
            {"name": "Audiomack Day Pass", "price": 3, "input_type": "email", "active": True},
            {"name": "Audiomack Monthly Pass", "price": 25, "input_type": "email", "active": True}
        ],
         "tinder": [
            {"name": "Standard 1 Week - Plus", "price":25, "input_type": "phone", "active": True},
            {"name": "Standard 1 Week - Gold", "price": 35, "input_type": "phone", "active": True},
            {"name": "Standard 1 Month - Plus", "price": 42, "input_type": "phone", "active": True},
            {"name": "Standard 1 Month - Gold", "price": 55, "input_type": "phone", "active": True},
        ],
        "fcmobile": [
            {"name": "40 FC Points", "price": 7, "input_type": "id", "active": True},
            {"name": "100 FC Points", "price": 17, "input_type": "id", "active": True},
            {"name": "520 FC Points", "price": 80, "input_type": "id", "active": True},
            {"name": "1070 FC Points", "price": 160, "input_type": "id", "active": True},
            {"name": "2200 FC Points", "price": 310, "input_type": "id", "active": True},
            {"name": "5750 FC Points", "price": 775, "input_type": "id", "active": True},
            {"name": "12000 FC Points", "price": 1570, "input_type": "id", "active": True},
        ],
        "freefire": [
            {"name": "100 Diamonds", "price": 18, "input_type": "id", "active": True},
            {"name": "210 Diamonds", "price": 32, "input_type": "id", "active": True},
            {"name": "530 Diamonds", "price": 72, "input_type": "id", "active": True},
            {"name": "1080 Diamonds", "price": 142, "input_type": "id", "active": True},
            {"name": "2200 Diamonds", "price": 275, "input_type": "id", "active": True},
        ],
        "codm": [
            {"name": "880 CP", "price": 145, "input_type": "id", "active": True},
            {"name": "30 CP", "price": 7, "input_type": "id", "active": True},
            {"name": "80 CP", "price": 15, "input_type": "id", "active": True},
            {"name": "420 CP", "price": 72, "input_type": "id", "active": True},
            {"name": "2400 CP", "price": 370, "input_type": "id", "active": True},
            {"name": "5000 CP", "price": 730, "input_type": "id", "active": True},
            {"name": "10800 CP", "price": 1440, "input_type": "id", "active": True},
            {"name": "21600 CP", "price": 2600, "input_type": "id", "active": True},
            {"name": "32400 CP", "price": 3800, "input_type": "id", "active": True},
            {"name": "54000 CP", "price": 6200, "input_type": "id", "active": True}
        ],
        "fcmobile.": [
            {"name": "39 Silver", "price": 8, "input_type": "id", "active": True},
            {"name": "99 Silver", "price": 18, "input_type": "id", "active": True},
            {"name": "499 Silver", "price": 82, "input_type": "id", "active": True},
            {"name": "1999 Silver", "price": 317, "input_type": "id", "active": True},
            {"name": "4999 Silver", "price": 780, "input_type": "id", "active": True},
            {"name": "9999 Silver", "price": 1550, "input_type": "id", "active": True},
        ],
        "codm.": [
            {"name": "Battle Pass Premium", "price": 40, "input_type": "id", "active": True},
            {"name": "Battle Pass Premium Bundle", "price": 93, "input_type": "id", "active": True}
        ],
         "marvelrivals": [
            {"name": "100 Lattices", "price": 15, "input_type": "id", "active": True},
            {"name": "500 Lattices", "price": 70, "input_type": "id", "active": True},
            {"name": "1000 Lattices", "price": 142, "input_type": "id", "active": True},
            {"name": "2180 Lattices", "price": 283, "input_type": "id", "active": True},
            {"name": "5680 Lattices", "price": 660, "input_type": "id", "active": True},
            {"name": "11680 Lattices", "price": 1310, "input_type": "id", "active": True},
        ],
        "deltaforce": [
            {"name": "18 Delta Coins", "price": 5.5, "input_type": "id", "active": True},
            {"name": "30 Delta Coins", "price": 9, "input_type": "id", "active": True},
            {"name": "60 Delta Coins", "price": 14, "input_type": "id", "active": True},
            {"name": "320 Delta Coins", "price": 60, "input_type": "id", "active": True},
            {"name": "460 Delta Coins", "price": 82, "input_type": "id", "active": True},
            {"name": "750 Delta Coins", "price": 115, "input_type": "id", "active": True},
        ],
        "honorofkings": [
            {"name": "16 Tokens", "price": 5, "input_type": "id", "active": True},
            {"name": "80 Tokens", "price": 15, "input_type": "id", "active": True},
            {"name": "240 Tokens", "price": 40, "input_type": "id", "active": True},
            {"name": "400 Tokens", "price": 65, "input_type": "id", "active": True},
            {"name": "560 Tokens", "price": 90, "input_type": "id", "active": True},
            {"name": "830 Tokens", "price": 130, "input_type": "id", "active": True},
        ],
        "arenabreakout": [
            {"name": "66 Bonds", "price": 15, "input_type": "id", "active": True},
            {"name": "335 Bonds", "price": 66, "input_type": "id", "active": True},
            {"name": "675 Bonds", "price": 130, "input_type": "id", "active": True},
            {"name": "1690 Bonds", "price": 317, "input_type": "id", "active": True},
            {"name": "3400 Bonds", "price": 630, "input_type": "id", "active": True},
            {"name": "6820 Bonds", "price": 1255, "input_type": "id", "active": True},
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