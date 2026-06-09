"""
Ledgehold Merchant Routes Module
Handles merchant self-service write operations:
- MoMo number updates
- PIN reset initiation
- Listing creation
All routes require server-side validation of merchant identity.
"""

from flask import Blueprint, request, jsonify
import uuid
import datetime
import re
import traceback
from firebase_admin import firestore

merchant_bp = Blueprint('merchant', __name__)

# These will be set by app.py during initialization
db = None
APP_ID = None

def init_merchant_routes(database, app_id):
    global db, APP_ID
    db = database
    APP_ID = app_id


# ═══════════════════════════════════════════════════════════════
# UPDATE MOMO NUMBER
# ═══════════════════════════════════════════════════════════════

@merchant_bp.route('/api/merchant/update-momo', methods=['POST'])
def update_merchant_momo():
    """
    Updates the mobile money number for a verified merchant.
    The merchant must exist in verified_merchants.
    """
    data = request.json or {}
    merchant_id = data.get('merchantId')
    new_momo = data.get('momo')
    
    # Validate required fields
    if not merchant_id or not new_momo:
        return jsonify({"success": False, "error": "Missing required parameters (merchantId, momo)."}), 400
    
    # Validate phone number format: exactly 10 digits
    if not re.match(r'^\d{10}$', new_momo):
        return jsonify({"success": False, "error": "Phone number must be exactly 10 digits (e.g. 024XXXXXXX)."}), 400
    
    try:
        merchant_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('verified_merchants').document(merchant_id)
        )
        
        merchant_doc = merchant_ref.get()
        if not merchant_doc.exists:
            return jsonify({"success": False, "error": "Merchant account not found. Please contact support."}), 404
        
        # Update the MoMo number
        merchant_ref.update({
            "momo": new_momo,
            "momo_updated_at": firestore.SERVER_TIMESTAMP
        })
        
        print(f"📱 MoMo updated for merchant {merchant_id}: {new_momo[:3]}****{new_momo[-3:]}")
        return jsonify({
            "success": True,
            "message": "Mobile money number updated successfully."
        }), 200
        
    except Exception as e:
        print(f"❌ MoMo update error for {merchant_id}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "An internal error occurred. Please try again."}), 500


# ═══════════════════════════════════════════════════════════════
# INITIATE PIN RESET
# ═══════════════════════════════════════════════════════════════

@merchant_bp.route('/api/merchant/initiate-pin-reset', methods=['POST'])
def initiate_pin_reset():
    """
    Initiates a PIN reset for a merchant by verifying their MoMo number.
    Clears the current PIN and setup_complete flag, generates a reset token,
    and returns a CMS redirect URL.
    """
    data = request.json or {}
    merchant_id = data.get('merchantId')
    momo = data.get('momo')
    
    # Validate required fields
    if not merchant_id or not momo:
        return jsonify({"success": False, "error": "Missing required parameters (merchantId, momo)."}), 400
    
    try:
        merchant_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('verified_merchants').document(merchant_id)
        )
        
        merchant_doc = merchant_ref.get()
        if not merchant_doc.exists:
            return jsonify({"success": False, "error": "Merchant account not found."}), 404
        
        merchant_data = merchant_doc.to_dict()
        
        # Verify the MoMo number matches what's on file
        stored_momo = merchant_data.get('momo', '')
        if stored_momo != momo:
            print(f"🛡️ PIN reset blocked: MoMo mismatch for {merchant_id}")
            return jsonify({
                "success": False, 
                "error": "The phone number provided does not match our records. Please check and try again."
            }), 403
        
        # Generate a unique reset token
        reset_token = str(uuid.uuid4())
        reset_expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
        
        # Clear PIN and set reset token
        merchant_ref.update({
            "pin": firestore.DELETE_FIELD,
            "setup_complete": firestore.DELETE_FIELD,
            "resetToken": reset_token,
            "resetExpiry": reset_expiry,
            "reset_initiated_at": firestore.SERVER_TIMESTAMP
        })
        
        # Build the CMS redirect URL
        import os
        host = os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:5000')
        redirect_url = f"https://{host}/cms?action=reset_pin&mid={merchant_id}&token={reset_token}"
        
        print(f"🔑 PIN reset initiated for {merchant_id}. Token expires at {reset_expiry}")
        return jsonify({
            "success": True,
            "message": "Identity verified. Redirecting to secure PIN setup.",
            "resetToken": reset_token,
            "redirectUrl": redirect_url
        }), 200
        
    except Exception as e:
        print(f"❌ PIN reset error for {merchant_id}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "An internal error occurred. Please try again."}), 500


# ═══════════════════════════════════════════════════════════════
# CREATE LISTING
# ═══════════════════════════════════════════════════════════════

@merchant_bp.route('/api/listings/create', methods=['POST'])
def create_listing():
    """
    Creates a new marketplace listing for a verified merchant.
    Accepts the full listing payload including images (URLs already uploaded to Cloudinary).
    Supports both standard single-price listings and variation-based listings.
    """
    data = request.json or {}
    
    merchant_id = data.get('merchantId')
    if not merchant_id:
        return jsonify({"success": False, "error": "Missing merchant ID. Please log in again."}), 400
    
    # Verify the merchant exists and is active
    try:
        merchant_doc = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('verified_merchants').document(merchant_id)
        ).get()
        
        if not merchant_doc.exists:
            return jsonify({"success": False, "error": "Your merchant account could not be verified. Please contact support."}), 403
        
        merchant_data = merchant_doc.to_dict()
        if not merchant_data.get('isApproved'):
            return jsonify({"success": False, "error": "Your merchant account is pending approval."}), 403
    except Exception as e:
        print(f"❌ Merchant verification failed: {e}")
        return jsonify({"success": False, "error": "Could not verify merchant status."}), 500
    
    # Validate required fields
    item_name = data.get('itemName', '').strip()
    price = data.get('price')
    img_urls = data.get('imgUrls', [])
    description = data.get('description', '').strip()
    university = data.get('university', '').strip()
    landmark = data.get('landmark', '').strip()
    availability = data.get('availability', 'Ready for Instant Pickup')
    
    if not item_name:
        return jsonify({"success": False, "error": "Item name is required."}), 400
    
    if not price or float(price) < 5.00:
        return jsonify({"success": False, "error": "Minimum listing price is GHS 5.00."}), 400
    
    if not img_urls or len(img_urls) == 0:
        return jsonify({"success": False, "error": "At least one product image is required."}), 400
    
    if not description:
        return jsonify({"success": False, "error": "A description of the item is required."}), 400
    
    if not university:
        return jsonify({"success": False, "error": "Campus/university is required."}), 400
    
    if not landmark:
        return jsonify({"success": False, "error": "Pickup landmark is required."}), 400
    
    # Build listing document
    has_variations = data.get('has_variations', False)
    variations = data.get('variations', [])
    is_bundled = data.get('is_bundled_pack', False)
    bundle_units = data.get('bundle_units_count', 1)
    
    # Validate variations if present
    if has_variations:
        if not variations or len(variations) == 0:
            return jsonify({"success": False, "error": "Variations mode is on but no variations were provided."}), 400
        
        # Validate each variation has required fields
        for i, var in enumerate(variations):
            if not var.get('label'):
                return jsonify({"success": False, "error": f"Variation #{i+1} is missing a label."}), 400
            if not var.get('price') or float(var.get('price', 0)) < 10.00:
                return jsonify({
                    "success": False, 
                    "error": f"Variation '{var.get('label', i+1)}' must have a price of at least GHS 10.00."
                }), 400
    
    try:
        listing_data = {
            "itemName": item_name,
            "price": float(price),
            "unit_price": data.get('unit_price', float(price)),
            "is_bundled_pack": is_bundled,
            "bundle_units_count": bundle_units,
            "has_variations": has_variations,
            "variations": variations,
            "stock": int(data.get('stock', 1)),
            "university": university,
            "description": description,
            "availability": availability,
            "schedule": data.get('schedule', ''),
            "landmark": landmark,
            "imgUrl": img_urls[0] if img_urls else '',
            "imgUrls": img_urls,
            "merchantId": merchant_id,
            "seller": merchant_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": "active"
        }
        
        # Write to Firestore
        ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('market_listings').add(listing_data)
        )
        
        listing_id = ref[1].id
        
        print(f"📦 Listing created: {item_name} (ID: {listing_id}) by {merchant_id}")
        return jsonify({
            "success": True,
            "listingId": listing_id,
            "message": "Your item has been published to the marketplace."
        }), 200
        
    except Exception as e:
        print(f"❌ Listing creation error for {merchant_id}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "An error occurred while publishing your listing. Please try again."}), 500
    
@merchant_bp.route('/api/listings/update', methods=['POST'])
def update_listing():
    """
    Updates an existing marketplace listing. Only the listing owner can update.
    """
    data = request.json or {}
    merchant_id = data.get('merchantId')
    listing_id = data.get('listingId')
    
    if not merchant_id or not listing_id:
        return jsonify({"success": False, "error": "Missing required parameters."}), 400
    
    try:
        listing_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('market_listings').document(listing_id)
        )
        
        listing_doc = listing_ref.get()
        if not listing_doc.exists:
            return jsonify({"success": False, "error": "Listing not found."}), 404
        
        # Verify ownership
        listing_data = listing_doc.to_dict()
        if listing_data.get('merchantId') != merchant_id:
            return jsonify({"success": False, "error": "Unauthorized. This is not your listing."}), 403
        
        # Build update payload (only include fields that were sent)
        update_data = {}
        
        if 'itemName' in data:
            name = data.get('itemName', '').strip()
            if not name:
                return jsonify({"success": False, "error": "Item name cannot be empty."}), 400
            update_data['itemName'] = name
        
        if 'price' in data:
            price = data.get('price')
            if price is not None:
                price_val = float(price)
                if price_val < 5.00:
                    return jsonify({"success": False, "error": "Minimum price is GHS 5.00."}), 400
                update_data['price'] = price_val
        
        if 'stock' in data:
            stock = data.get('stock')
            if stock is not None:
                stock_val = int(stock)
                if stock_val < 0:
                    return jsonify({"success": False, "error": "Stock cannot be negative."}), 400
                update_data['stock'] = stock_val
        
        if 'description' in data:
            update_data['description'] = data.get('description', '').strip()
        
        if not update_data:
            return jsonify({"success": False, "error": "No fields to update."}), 400
        
        update_data['updatedAt'] = firestore.SERVER_TIMESTAMP
        
        listing_ref.update(update_data)
        
        print(f"📝 Listing updated: {listing_id} by {merchant_id}")
        return jsonify({"success": True, "message": "Listing updated."}), 200
        
    except Exception as e:
        print(f"❌ Listing update error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "An internal error occurred."}), 500
    
@merchant_bp.route('/api/listings/delete', methods=['POST'])
def delete_listing():
    """
    Removes a listing from the marketplace. Only the listing owner can delete.
    """
    data = request.json or {}
    merchant_id = data.get('merchantId')
    listing_id = data.get('listingId')
    
    if not merchant_id or not listing_id:
        return jsonify({"success": False, "error": "Missing required parameters."}), 400
    
    try:
        listing_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('market_listings').document(listing_id)
        )
        
        listing_doc = listing_ref.get()
        if not listing_doc.exists:
            return jsonify({"success": False, "error": "Listing not found."}), 404
        
        # Verify ownership
        listing_data = listing_doc.to_dict()
        if listing_data.get('merchantId') != merchant_id:
            return jsonify({"success": False, "error": "Unauthorized. This is not your listing."}), 403
        
        listing_ref.delete()
        
        print(f"🗑️ Listing deleted: {listing_id} by {merchant_id}")
        return jsonify({"success": True, "message": "Listing removed from marketplace."}), 200
        
    except Exception as e:
        print(f"❌ Listing delete error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "An internal error occurred."}), 500
    
# ── REQUEST MOMO CHANGE ──
@merchant_bp.route('/api/merchant/request-momo-change', methods=['POST'])
def request_momo_change():
    """
    Submits a MoMo number change request with KYC re-verification.
    Creates a document in momo_change_requests for admin review.
    """
    data = request.json or {}
    merchant_id = data.get('merchantId')
    old_momo = data.get('oldMomo')
    new_momo = data.get('newMomo')
    id_url = data.get('idUrl')
    selfie_url = data.get('selfieUrl')
    
    if not all([merchant_id, old_momo, new_momo, id_url, selfie_url]):
        return jsonify({"success": False, "error": "Missing required fields."}), 400
    
    if not re.match(r'^\d{10}$', new_momo):
        return jsonify({"success": False, "error": "Invalid phone number format."}), 400
    
    if old_momo == new_momo:
        return jsonify({"success": False, "error": "New number must be different from current."}), 400
    
    try:
        # Verify merchant exists
        merchant_doc = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('verified_merchants').document(merchant_id)
        ).get()
        
        if not merchant_doc.exists:
            return jsonify({"success": False, "error": "Merchant not found."}), 404
        
        # Verify old MoMo matches what's on file
        merchant_data = merchant_doc.to_dict()
        if merchant_data.get('momo') != old_momo:
            return jsonify({"success": False, "error": "Current MoMo number does not match records."}), 403
        
        # Check for existing pending request
        existing = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('momo_change_requests')
              .where('merchantId', '==', merchant_id)
              .where('status', '==', 'pending')
              .limit(1).get()
        )
        
        if existing and len(existing) > 0:
            return jsonify({
                "success": False, 
                "error": "You already have a pending MoMo change request. Please wait for it to be reviewed."
            }), 409
        
        # Create change request
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('momo_change_requests').add({
            "merchantId": merchant_id,
            "oldMomo": old_momo,
            "newMomo": new_momo,
            "idUrl": id_url,
            "selfieUrl": selfie_url,
            "status": "pending",
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        
        print(f"🔒 MoMo change requested: {merchant_id} — {old_momo[:3]}**** → {new_momo[:3]}****")
        
        # ── DISPATCH EMAIL ALERT ──
        try:
            import resend
            import os
            
            old_display = f"0{old_momo[-9:]}" if len(old_momo) >= 10 else old_momo
            new_display = f"0{new_momo[-9:]}" if len(new_momo) >= 10 else new_momo
            
            email_body = f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; color: #0f172a;">
                <h3 style="color: #f59e0b; margin-top: 0; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">
                    🔒 MoMo Change Request — Awaiting Review
                </h3>
                
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr style="background: #f8fafc;">
                        <td style="padding: 10px; border: 1px solid #e2e8f0;"><strong>Merchant ID</strong></td>
                        <td style="padding: 10px; border: 1px solid #e2e8f0;">{merchant_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #e2e8f0;"><strong>Current MoMo</strong></td>
                        <td style="padding: 10px; border: 1px solid #e2e8f0;">{old_display}</td>
                    </tr>
                    <tr style="background: #fef3c7;">
                        <td style="padding: 10px; border: 1px solid #e2e8f0;"><strong>Requested New MoMo</strong></td>
                        <td style="padding: 10px; border: 1px solid #e2e8f0; font-weight: 700; color: #d97706;">{new_display}</td>
                    </tr>
                </table>
                
                <h4 style="margin-top: 25px; margin-bottom: 10px; color: #475569; font-size: 12px; letter-spacing: 0.5px; text-transform: uppercase;">
                    Verification Documents
                </h4>
                <div style="display: flex; gap: 16px;">
                    <div style="flex: 1;">
                        <p style="font-size: 11px; color: #94a3b8; margin-bottom: 4px;">STUDENT ID</p>
                        <a href="{id_url}" target="_blank" style="display: block; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;">
                            <img src="{id_url}" style="width: 100%; max-height: 200px; object-fit: cover;" alt="Student ID">
                        </a>
                    </div>
                    <div style="flex: 1;">
                        <p style="font-size: 11px; color: #94a3b8; margin-bottom: 4px;">LIVE SELFIE</p>
                        <a href="{selfie_url}" target="_blank" style="display: block; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;">
                            <img src="{selfie_url}" style="width: 100%; max-height: 200px; object-fit: cover;" alt="Selfie">
                        </a>
                    </div>
                </div>
                
                <p style="text-align: center; margin-top: 30px;">
                    <a href="https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:5000')}/admin_controls" 
                       style="background: #0f172a; color: white; padding: 12px 28px; text-decoration: none; border-radius: 30px; font-weight: bold; font-size: 13px; display: inline-block;">
                        Review in Command Center
                    </a>
                </p>
                
                <p style="font-size: 11px; color: #94a3b8; margin-top: 30px; border-top: 1px dashed #e2e8f0; padding-top: 15px;">
                    This is an automated security alert. MoMo changes require manual admin approval before taking effect.
                </p>
            </div>
            """
            
            resend.Emails.send({
                "from": "Ledgehold Security <onboarding@resend.dev>",
                "to": ["ledgehold.business@gmail.com"],
                "subject": f"🔒 MoMo Change Request — {merchant_id}",
                "html": email_body
            })
            print(f"📧 MoMo change alert emailed for {merchant_id}")
            
        except Exception as email_err:
            print(f"⚠️ MoMo change email alert failed: {str(email_err)}")
        
        return jsonify({
            "success": True,
            "message": "Your request has been submitted for review. You'll be notified when it's approved."
        }), 200
        
    except Exception as e:
        print(f"❌ MoMo change request error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "An internal error occurred."}), 500
    
# ── JOIN ENDORSEMENT WAITLIST ──
@merchant_bp.route('/api/merchant/join-waitlist', methods=['POST'])
def join_endorsement_waitlist():
    """
    Adds a verified merchant to the endorsement waitlist after
    validating their credentials (name + PIN).
    """
    data = request.json or {}
    merchant_name = data.get('merchantName')
    pin = data.get('pin')
    
    if not merchant_name or not pin:
        return jsonify({"success": False, "error": "Missing required fields."}), 400
    
    try:
        # Query verified merchants by name
        merchants_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('verified_merchants')
        )
        
        query_snap = merchants_ref.where('fullName', '==', merchant_name).get()
        
        match_found = False
        merchant_id = None
        
        for doc in query_snap:
            merchant_data = doc.to_dict()
            # Compare SHA-256 hash of PIN
            import hashlib
            pin_hash = hashlib.sha256(pin.encode('utf-8')).hexdigest()
            if merchant_data.get('pin') == pin_hash:
                match_found = True
                merchant_id = doc.id
                break
        
        if not match_found or not merchant_id:
            return jsonify({"success": False, "error": "Invalid Name or PIN."}), 401
        
        # Check if already on waitlist
        existing = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('endorsement_waitlist')
              .document(merchant_id).get()
        )
        
        if existing.exists:
            return jsonify({"success": False, "error": "You are already on the waitlist."}), 409
        
        # Add to waitlist
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('endorsement_waitlist').document(merchant_id).set({
            "merchantId": merchant_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": "pending_audit"
        })
        
        print(f"Endorsement waitlist joined: {merchant_id}")
        return jsonify({"success": True, "message": "You've been added to the waitlist."}), 200
        
    except Exception as e:
        print(f"❌ Waitlist join error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "An internal error occurred."}), 500
    
# ── CMS PIN ACTIVATION ──
@merchant_bp.route('/api/merchant/activate-pin', methods=['POST'])
def activate_merchant_pin():
    """
    Sets a merchant's PIN during CMS self-onboarding.
    Only works if the merchant is approved and doesn't already have a PIN.
    """
    data = request.json or {}
    merchant_id = data.get('merchantId')
    pin_hash = data.get('pinHash')
    
    if not merchant_id or not pin_hash:
        return jsonify({"success": False, "error": "Missing required fields."}), 400
    
    try:
        merchant_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('verified_merchants').document(merchant_id)
        )
        
        merchant_doc = merchant_ref.get()
        if not merchant_doc.exists:
            return jsonify({"success": False, "error": "Invalid Merchant ID. Please check and try again."}), 404
        
        merchant_data = merchant_doc.to_dict()
        
        if not merchant_data.get('isApproved'):
            return jsonify({"success": False, "error": "Your application is still under review."}), 403
        
        if merchant_data.get('pin'):
            return jsonify({"success": False, "error": "This account has already been activated."}), 409
        
        merchant_ref.update({
            "pin": pin_hash,
            "activated_at": firestore.SERVER_TIMESTAMP,
            "setup_complete": True
        })
        
        return jsonify({"success": True, "message": "PIN activated successfully."}), 200
        
    except Exception as e:
        print(f"❌ CMS PIN activation error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "An internal error occurred."}), 500