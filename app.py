from flask import Flask, render_template, request, jsonify, redirect
import os
import random
import datetime
import firebase_admin
import traceback
import redis as redis_client
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from firebase_admin import credentials, firestore, initialize_app
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter

# Load environment variables
load_dotenv(override=True)

app = Flask(__name__)

redis_storage_url = os.getenv("REDIS_URL")

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=redis_storage_url or "memory://",
    default_limits=["5000 per day", "200 per hour"],
    default_limits_exempt_when=lambda: request.path == '/healthz'
)

# ── ENVIRONMENT CONFIGURATION ──
ADMIN_IDS = [id.strip() for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]
ADMIN_PINS = [pin.strip() for pin in os.environ.get("ADMIN_PINS", "").split(",") if pin.strip()]
COMPLIANCE_MODE = False
APP_ID = os.getenv('__app_id', 'ledgehold-ghana1')

# ── FINANCIAL API URL (points to Ledgehold's server) ──
FINANCIAL_API_URL = os.environ.get("FINANCIAL_API_URL", "")


# ── FIREBASE INITIALIZATION ──
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


# ── IMPORT & INITIALIZE MODULES ──
from admin_routes import admin_bp, init_admin_routes
from merchant_routes import merchant_bp, init_merchant_routes

init_admin_routes(db, APP_ID, ADMIN_IDS, ADMIN_PINS)
init_merchant_routes(db, APP_ID)

app.register_blueprint(admin_bp)
app.register_blueprint(merchant_bp)


# ── CONTEXT PROCESSOR ──
@app.context_processor
def inject_globals():
    return {
        "compliance_mode": COMPLIANCE_MODE,
        "FINANCIAL_API_URL": FINANCIAL_API_URL,
    }


# ── SHARED HELPERS ──
def get_firebase_context():
    """Consolidated context provider for frontend templates"""
    return {
        "__app_id": APP_ID,
        "__firebase_config": os.environ.get("__firebase_config", "{}"),
        "IMGBB_API_KEY": os.environ.get("IMGBB_API_KEY", ""),
        "compliance_mode": COMPLIANCE_MODE,
        "campus_locations": CAMPUS_PICKUP_LOCATIONS,
        "FINANCIAL_API_URL": FINANCIAL_API_URL,
    }


# ═══════════════════════════════════════════════════════════════
# PAGE ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def home():
    source = request.args.get('ref')
    welcome_msg = None
    welcome_type = "info"

    if source == 'front':
        welcome_msg = "Curiosity rewarded! Explore our student specials."
        welcome_type = "success"
    elif source == 'back' or source == 'tshirt':
        welcome_msg = "Hey Scholar! Check out our Student Specials below."
        welcome_type = "primary"

    food_is_active = datetime.datetime.now().weekday() >= 4
    return render_template('home.html',
                           welcome_msg=welcome_msg,
                           welcome_type=welcome_type,
                           food_active=food_is_active)


@app.route('/healthz')
def health_check():
    return "OK", 200


@app.route('/admin_controls')
def admin_controls():
    return render_template('admin.html', **get_firebase_context())


@app.route('/api/marketplace/listings', methods=['GET'])
def get_all_listings():
    """Fetches real-time listings from the Firestore silo."""
    try:
        takedown_ref = db.collection('artifacts').document(APP_ID)\
                         .collection('public').document('data')\
                         .collection('takedown_registry')
        blocked_ids = [doc.id for doc in takedown_ref.stream()]

        listings_ref = db.collection('artifacts').document(APP_ID)\
                         .collection('public').document('data')\
                         .collection('market_listings')
        
        all_items = []
        for doc in listings_ref.stream():
            data = doc.to_dict()
            if data.get('status') == 'active' and doc.id not in blocked_ids:
                data['id'] = doc.id
                all_items.append(data)

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


@app.route('/financial_view')
def financial_vault():
    """Serves the isolated Financial Intelligence & Dispute Resolution Node"""
    return render_template('financial_view.html', **get_firebase_context())


@app.route('/verify_order')
def verify_order_landing():
    return render_template('buyer_verify.html', **get_firebase_context())


@app.route('/update_momo')
def update_momo():
    return render_template('update_momo.html', **get_firebase_context())


@app.route('/foodrun')
def food_run_page():
    today_idx = datetime.datetime.now().weekday()
    today_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][today_idx]
    
    if today_idx >= 4:
        state = "open"
        menu = [
            {"item": "KFC Streetwise 2 (Rice)", "price": 90.00, "img": "https://cdn.tictuk.com/staging/fc9ab8a5-b3d3-4cf6-0e30-555e691086bf/7824c8df-6c6b-d80d-7e44-877899c2ed9b.jpeg?a=d1cb9c76-1f98-19c4-1a27-597c125b2738", "description": "Classic KFC chicken with seasoned rice and signature sauce", "prep_time": "25"},
            {"item": "Waakye Special (Egg + Fish)", "price": 30.00, "img": "https://tse2.mm.bing.net/th/id/OIP.u3ot8N9zmflWBBd4S4Lq-QHaJL?cb=ucfimg2&ucfimg=1&rs=1&pid=ImgDetMain&o=7&rm=3", "description": "Traditional Ghanaian waakye with boiled egg and fried fish", "prep_time": "20"},
            {"item": "Pizza (Medium Size)", "price": 120.00, "img": "https://images.unsplash.com/photo-1513104890138-7c749659a591?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=80", "description": "Mid-sized pizza with surprise toppings", "prep_time": "5"},
            {"item": "Jollof Rice + Chicken", "price": 45.00, "img": "https://th.bing.com/th/id/OIP.n_wJL9qZ16lh_uiRCqNiUgHaHa?w=197&h=197&c=7&r=0&o=7&cb=ucfimg2&dpr=1.5&pid=1.7&rm=3&ucfimg=1", "description": "Spicy Ghanaian jollof rice with grilled chicken", "prep_time": "25"},
            {"item": "Fried Rice + Chicken", "price": 45.00, "img": "https://th.bing.com/th/id/OIP.RfVI9SuTBNY6oWetN8uMXgHaFO?w=252&h=180&c=7&r=0&o=7&cb=ucfimg2&dpr=1.5&pid=1.7&rm=3&ucfimg=1", "description": "Fried rice with vegetables and grilled chicken", "prep_time": "25"},
            {"item": "Banku + Tilapia", "price": 40.00, "img": "https://th.bing.com/th/id/OIP.6rFklsZZtFe5ylXkNsz1hgHaHa?w=173&h=180&c=7&r=0&o=7&cb=ucfimg2&dpr=1.5&pid=1.7&rm=3&ucfimg=1", "description": "Fresh tilapia with banku and pepper sauce", "prep_time": "30"},
            {"item": "Plain Rice + Chicken Stew", "price": 35.00, "img": "https://th.bing.com/th/id/OIP.kBNJKGnK8BFTISvoUVRlIwHaFI?w=251&h=180&c=7&r=0&o=7&cb=ucfimg2&dpr=1.5&pid=1.7&rm=3&ucfimg=1", "description": "Steamed rice with rich chicken stew", "prep_time": "20"}
        ]
        random.shuffle(menu)
    else:
        state = "closed"
        menu = []

    return render_template('foodrun.html', state=state, menu=menu, today_name=today_name, today_idx=today_idx)


@app.route('/marketing_toolkit')
def marketing():
    cloudinary_name = os.getenv('CLOUDINARY_CLOUD_NAME')
    return render_template('marketing_toolkit.html', CLOUDINARY_CLOUD_NAME=cloudinary_name, **get_firebase_context())


@app.route('/endorsement')
def endorsement():
    return render_template('endorsement.html', **get_firebase_context())


@app.route('/marketplace')
def marketplace():
    return render_template('marketplace.html', **get_firebase_context())


@app.route('/inventory_management')
def inventory():
    return render_template('inventory_management.html', **get_firebase_context())


@app.route('/seller_onboarding')
@app.route('/onboarding')
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
    return render_template('cms.html', **get_firebase_context())


@app.route('/merchant_dashboard')
def merchant_dashboard():
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
    listing_id = request.args.get('id')
    authoritative_img = ""

    if listing_id:
        try:
            listing_doc = (
                db.collection('artifacts').document(APP_ID)
                  .collection('public').document('data')
                  .collection('market_listings').document(listing_id)
            ).get()
            
            if listing_doc.exists:
                listing_data = listing_doc.to_dict()
                client_img = request.args.get('img', '').strip()

                if client_img:
                    authoritative_img = client_img
                elif 'imgUrls' in listing_data and isinstance(listing_data['imgUrls'], list) and len(listing_data['imgUrls']) > 0:
                    authoritative_img = listing_data['imgUrls'][0]
                else:
                    authoritative_img = listing_data.get('imgUrl', '')
                    
        except Exception as e:
            print(f"⚠️ SERVER CHECKOUT IMAGE CAPTURE WARNING: {str(e)}")

    return render_template(
        'checkout.html', 
        paystack_pub_key=pub_key, 
        authoritative_img=authoritative_img,
        **get_firebase_context()
    )


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/item')
def item_detail():
    listing_id = request.args.get('id')
    
    if not listing_id:
        return redirect('/marketplace')
    
    try:
        listing_doc = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('market_listings').document(listing_id)
        ).get()
        
        if not listing_doc.exists:
            return "Listing not found.", 404
        
        item = listing_doc.to_dict()
        item['id'] = listing_id

        if item.get('has_variations') and item.get('variations'):
            first_var = item['variations'][0]
            item['variation_type'] = first_var.get('type', 'Available Options')
        
        all_images = []
        
        if item.get('imgUrls') and isinstance(item['imgUrls'], list) and len(item['imgUrls']) > 0:
            all_images.extend(item['imgUrls'])
        elif item.get('imgUrl'):
            all_images.append(item['imgUrl'])
        
        if item.get('has_variations') and item.get('variations'):
            for var in item['variations']:
                if var.get('imgUrls') and isinstance(var['imgUrls'], list):
                    for img in var['imgUrls']:
                        if img and img not in all_images:
                            all_images.append(img)
                elif var.get('imgUrl') and var['imgUrl'] not in all_images:
                    all_images.append(var['imgUrl'])
        
        import re
        merchant_id = item.get('merchantId', '')
        merchant_display_name = re.sub(r'\s\d{4}$', '', merchant_id).strip() if merchant_id else 'Verified Merchant'
        
        merchant_items = []
        if merchant_id:
            merchant_listings = (
                db.collection('artifacts').document(APP_ID)
                  .collection('public').document('data')
                  .collection('market_listings')
                  .where(filter=FieldFilter('merchantId', '==', merchant_id))
                  .where(filter=FieldFilter('status', '==', 'active'))
                  .limit(7)
                  .stream()
            )
            for m in merchant_listings:
                if m.id != listing_id:
                    data = m.to_dict()
                    data['id'] = m.id
                    merchant_items.append(data)
                    if len(merchant_items) >= 6:
                        break
        
        random_items = []
        random_listings = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('market_listings')
              .where(filter=FieldFilter('status', '==', 'active'))
              .limit(20)
              .stream()
        )
        for r in random_listings:
            data = r.to_dict()
            if r.id != listing_id and data.get('merchantId') != merchant_id:
                data['id'] = r.id
                random_items.append(data)
                if len(random_items) >= 6:
                    break
        
        return render_template(
            'item_detail.html',
            item=item,
            all_images=all_images,
            merchant_display_name=merchant_display_name,
            merchant_items=merchant_items,
            random_items=random_items,
            **get_firebase_context()
        )
        
    except Exception as e:
        print(f"Item detail error: {e}")
        traceback.print_exc()
        return "An error occurred loading this listing.", 500


@app.route('/merchant_guide')
def guide():
    return render_template('merchant_guide.html')


@app.route('/success')
def payment_success():
    tx_reference = request.args.get('ref')
    seller_phone = ""
    
    if tx_reference:
        try:
            order_query = db.collection('artifacts').document(APP_ID)\
                            .collection('public').document('data')\
                            .collection('orders')\
                            .where('paystack_ref', '==', tx_reference).limit(1).get()
            
            if order_query and len(order_query) > 0:
                order_data = order_query[0].to_dict()
                listing_id = order_data.get('listing_id')
                
                if listing_id:
                    listing_doc = db.collection('artifacts').document(APP_ID)\
                                    .collection('public').document('data')\
                                    .collection('market_listings').document(listing_id).get()
                    
                    if listing_doc.exists:
                        merchant_id = listing_doc.to_dict().get('merchantId')
                        
                        if merchant_id:
                            merchant_doc = db.collection('artifacts').document(APP_ID)\
                                             .collection('public').document('data')\
                                             .collection('verified_merchants').document(merchant_id).get()
                            
                            if merchant_doc.exists:
                                merchant_data = merchant_doc.to_dict()
                                raw_phone = merchant_data.get('momo') or merchant_data.get('phone') or ''
                                
                                if raw_phone and len(raw_phone) >= 10:
                                    if raw_phone.startswith('233'):
                                        seller_phone = '0' + raw_phone[3:]
                                    elif raw_phone.startswith('0'):
                                        seller_phone = raw_phone
                                    else:
                                        seller_phone = '0' + raw_phone
                                
        except Exception as e:
            print(f"⚠️ SECURITY FORENSICS LOG INGESTION ERROR: {str(e)}")

    return render_template(
        'success.html',
        seller_phone=seller_phone,
        **get_firebase_context()
    )


@app.route('/about_us')
def about():
    return render_template('about_us.html')


@app.route('/terms')
def terms_page():
    return render_template('terms.html')


@app.route('/tv')
def tv_page():
    if COMPLIANCE_MODE:
        return render_template('maintenance.html', page_name="Entertainment Hub")

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
    return render_template('tv.html', videos=movies)


@app.route('/buy/<network>')
def product_page(network):
    pricing = {
        "mtn": [
            {"name": "1GB Non-Expiry", "price": 14, "input_type": "phone", "active": True}, 
            {"name": "2GB Non-Expiry", "price": 29, "input_type": "phone", "active": True},
            {"name": "3GB Non-Expiry", "price": 43, "input_type": "phone", "active": True},
            {"name": "4GB Non-Expiry", "price": 58, "input_type": "phone", "active": True},
            {"name": "5GB Non-Expiry", "price": 73, "input_type": "phone", "active": True},
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
    input_type = selected_bundles[0]['input_type'] if selected_bundles else 'phone'
    
    return render_template('product.html', 
                           network_name=network.upper(), 
                           bundles=selected_bundles,
                           input_type=input_type,
                           is_voucher=is_voucher)


# ── ERROR HANDLERS ──
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html', **get_firebase_context()), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html', **get_firebase_context()), 500


# ═══════════════════════════════════════════════════════════════
# CAMPUS PICKUP LOCATIONS — VERIFIED SAFE EXCHANGE POINTS
# ═══════════════════════════════════════════════════════════════

CAMPUS_PICKUP_LOCATIONS = {
    "UMaT - Essikado": [
        "Main Administration Block",
        "Campus Canteen / Food Court",
        "Library Entrance",
        "Main Campus Gate (Security Post)",
        "Round Summer Hut",
    ],
    "KNUST Main Campus": [
        "Commercial Area",
        "Brunei Complex Forecourt",
        "College of Engineering (CoE) Pavilion",
        "KNUST Main Library Entrance",
        "Unity Hall (Conti) Main Gate",
        "Republic Hall Mini Market",
        "Great Hall Foyer",
    ],
    "UCC": [
        "Science Market Square",
        "Sam Jonah Library Forecourt",
        "Old Site Taxi Rank",
        "Casley Hayford (Casford) Hall Gate",
        "Valco Hall Main Entrance",
        "Nduom School of Business (Main Gate)",
        "SMS Auditorium",
        "Amissah Arthur Language Centre",
    ],
    "UG Legon": [
        "Banking Square",
        "Balme Library (Main Entrance)",
        "Bush Canteen",
        "Pentagon Hostels (Main Gate)",
        "UGBS Courtyard",
        "Mensah Sarbah Hall Gate",
        "Akuafo Hall Roundabout",
    ],
}

DEFAULT_LOCATIONS = [
    "Main Administration Block",
    "Central Campus Library",
    "SRC / Student Union Building",
    "Main Campus Food Court / Canteen",
    "Campus Security Post / Main Gate",
]

# ═══════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))