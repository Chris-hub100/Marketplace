"""
Ledgehold Admin Routes Module
Handles all administrative write operations for merchant management,
marketplace moderation, notifications, and security configuration.
All routes require admin authentication via ID and PIN.
"""

from flask import Blueprint, request, jsonify
import secrets
import datetime
import traceback
from firebase_admin import firestore

admin_bp = Blueprint('admin', __name__)

# These will be set by app.py during initialization
db = None
APP_ID = None
ADMIN_ID = None
ADMIN_PIN = None

def init_admin_routes(database, app_id, admin_ids, admin_pins):
    global db, APP_ID, ADMIN_IDS, ADMIN_PINS
    db = database
    APP_ID = app_id
    ADMIN_IDS = admin_ids
    ADMIN_PINS = admin_pins


def validate_admin(admin_id, admin_pin):
    for i, aid in enumerate(ADMIN_IDS):
        if admin_id == aid and i < len(ADMIN_PINS) and admin_pin == ADMIN_PINS[i]:
            return True
    return False


def send_professional_sms(to_number, message_content):
    """Dispatches SMS via Hubtel API using the shared auth token."""
    import requests
    import os
    from base64 import b64encode
    
    hub_id = os.environ.get('HUBTEL_CLIENT_ID')
    hub_secret = os.environ.get('HUBTEL_CLIENT_SECRET')
    hub_auth = b64encode(f"{hub_id}:{hub_secret}".encode()).decode()
    
    url = "https://smsc.hubtel.com/v1/messages/send"
    headers = {
        "Authorization": f"Basic {hub_auth}",
        "Content-Type": "application/json"
    }
    payload = {
        "From": "Ledgehold",
        "To": to_number,
        "Content": message_content
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"❌ Hubtel Connection Exception: {str(e)}")
        return False


# ═══════════════════════════════════════════════════════════════
# APPROVE MERCHANT
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/approve-merchant', methods=['POST'])
def approve_merchant():
    """
    Moves a merchant from pending_merchants to verified_merchants,
    generates an onboarding token, and triggers an SMS invitation.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    doc_id = data.get('docId')
    if not doc_id:
        return jsonify({"success": False, "error": "Missing docId."}), 400
    
    try:
        # Fetch pending document
        pending_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('pending_merchants').document(doc_id)
        )
        pending_doc = pending_ref.get()
        if not pending_doc.exists:
            return jsonify({"success": False, "error": "Pending request not found."}), 404
        
        pending_data = pending_doc.to_dict()
        merchant_id = pending_data.get('merchantId')
        phone = pending_data.get('momo')
        full_name = pending_data.get('fullName')
        university = pending_data.get('university')
        
        if not merchant_id:
            return jsonify({"success": False, "error": "Pending document missing merchantId."}), 400
        
        # Generate onboarding token
        token = secrets.token_hex(4)
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
        
        # Write token to onboarding_tokens collection
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('onboarding_tokens').document(token).set({
            "token": token,
            "expiresAt": expires_at,
            "status": "active",
            "used": False,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "createdBy": data.get('adminId'),
            "merchantId": merchant_id
        })
        
        # Create verified merchant document
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('verified_merchants').document(merchant_id).set({
            **pending_data,
            "isApproved": True,
            "approvedAt": firestore.SERVER_TIMESTAMP,
            "status": "active",
            "university": university
        })
        
        # Delete from pending queue
        pending_ref.delete()
        
        # Send SMS invitation
        try:
            import os
            cms_link = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'market-place-gx9a.onrender.com')}/cms?token={token}"
            message = f"Hello {full_name}, your Merchant Account has been approved! ID: {merchant_id}. Setup your Account PIN here to log into your dashboard: {cms_link}"
            
            if phone:
                send_professional_sms(phone, message)
                print(f"📨 Approval SMS sent to {phone} for merchant {merchant_id}")
            else:
                print(f"⚠️ No phone number found for {merchant_id} — SMS skipped.")
        except Exception as sms_err:
            print(f"⚠️ Approval SMS failed: {str(sms_err)}")
        
        print(f"✅ Merchant approved: {merchant_id}")
        return jsonify({
            "success": True, 
            "merchantId": merchant_id,
            "token": token
        }), 200
        
    except Exception as e:
        print(f"❌ Approval error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# DENY MERCHANT
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/deny-merchant', methods=['POST'])
def deny_merchant():
    """
    Removes a merchant from the pending queue and optionally sends
    a rejection SMS.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    doc_id = data.get('docId')
    if not doc_id:
        return jsonify({"success": False, "error": "Missing docId."}), 400
    
    try:
        # Fetch pending doc for SMS details before deletion
        pending_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('pending_merchants').document(doc_id)
        )
        pending_doc = pending_ref.get()
        
        if pending_doc.exists:
            pending_data = pending_doc.to_dict()
            phone = pending_data.get('momo')
            full_name = pending_data.get('fullName')
            
            # Send rejection SMS
            try:
                if phone and full_name:
                    message = f"Hello {full_name}, we were unable to verify your Merchant application due to unclear details. Feel free to reapply ensuring that your ID and selfie images are clear."
                    send_professional_sms(phone, message)
                    print(f"📨 Rejection SMS sent to {phone}")
            except Exception as sms_err:
                print(f"⚠️ Rejection SMS failed: {str(sms_err)}")
        
        # Delete from pending queue
        pending_ref.delete()
        
        print(f"✅ Merchant denied and removed: {doc_id}")
        return jsonify({"success": True}), 200
        
    except Exception as e:
        print(f"❌ Denial error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# TAKEDOWN LISTING
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/takedown-listing', methods=['POST'])
def takedown_listing():
    """
    Permanently removes a listing from the marketplace.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    listing_id = data.get('listingId')
    if not listing_id:
        return jsonify({"success": False, "error": "Missing listingId."}), 400
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('market_listings').document(listing_id).delete()
        
        print(f"✅ Listing takedown: {listing_id}")
        return jsonify({"success": True, "message": f"Listing {listing_id} removed."}), 200
        
    except Exception as e:
        print(f"❌ Takedown error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# RESET MERCHANT PIN
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/reset-merchant-pin', methods=['POST'])
def reset_merchant_pin():
    """
    Clears a merchant's PIN and setup_complete flag, forcing them
    to re-onboard via the CMS.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    merchant_id = data.get('merchantId')
    if not merchant_id:
        return jsonify({"success": False, "error": "Missing merchantId."}), 400
    
    try:
        merchant_ref = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('verified_merchants').document(merchant_id)
        )
        
        merchant_doc = merchant_ref.get()
        if not merchant_doc.exists:
            return jsonify({"success": False, "error": "Merchant not found."}), 404
        
        merchant_ref.update({
            "pin": firestore.DELETE_FIELD,
            "setup_complete": firestore.DELETE_FIELD,
            "last_reset": firestore.SERVER_TIMESTAMP,
            "reset_by": data.get('adminId')
        })
        
        print(f"✅ PIN reset for merchant: {merchant_id}")
        return jsonify({"success": True, "message": f"PIN cleared for {merchant_id}."}), 200
        
    except Exception as e:
        print(f"❌ PIN reset error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# REVOKE MERCHANT
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/revoke-merchant', methods=['POST'])
def revoke_merchant():
    """
    Permanently removes a merchant and ALL their listings from the platform.
    Uses a batched write for atomicity.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    merchant_id = data.get('merchantId')
    if not merchant_id:
        return jsonify({"success": False, "error": "Missing merchantId."}), 400
    
    try:
        # Find all listings by this merchant
        listings = (
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('market_listings')
              .where('merchantId', '==', merchant_id).get()
        )
        
        # Batch delete listings and merchant document
        batch = db.batch()
        listing_count = 0
        
        for doc in listings:
            batch.delete(doc.reference)
            listing_count += 1
        
        batch.delete(
            db.collection('artifacts').document(APP_ID)
              .collection('public').document('data')
              .collection('verified_merchants').document(merchant_id)
        )
        
        batch.commit()
        
        print(f"✅ Merchant revoked: {merchant_id} ({listing_count} listings removed)")
        return jsonify({
            "success": True, 
            "message": f"Merchant {merchant_id} and {listing_count} listings permanently removed.",
            "listingsRemoved": listing_count
        }), 200
        
    except Exception as e:
        print(f"❌ Revoke error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# SEND MERCHANT NOTIFICATION
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/send-notification', methods=['POST'])
def send_notification():
    """
    Creates or updates a notification document for a specific merchant.
    The merchant dashboard listens to this document in real-time.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    target = data.get('target')
    message = data.get('message')
    notif_type = data.get('type', 'primary')
    
    if not target or not message:
        return jsonify({"success": False, "error": "Missing target or message."}), 400
    
    # Validate notification type
    valid_types = ['primary', 'warning', 'success', 'danger']
    if notif_type not in valid_types:
        notif_type = 'primary'
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('merchant_notifications').document(target).set({
            "message": message,
            "type": notif_type,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "sent_by": data.get('adminId')
        })
        
        print(f"📨 Notification sent to {target}: [{notif_type}] {message[:50]}...")
        return jsonify({"success": True, "message": f"Notification delivered to {target}."}), 200
        
    except Exception as e:
        print(f"❌ Notification error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# DELETE MERCHANT NOTIFICATION
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/delete-notification', methods=['POST'])
def delete_notification():
    """
    Removes an active notification from a merchant's dashboard.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    doc_id = data.get('docId')
    if not doc_id:
        return jsonify({"success": False, "error": "Missing docId."}), 400
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('merchant_notifications').document(doc_id).delete()
        
        print(f"✅ Notification cleared: {doc_id}")
        return jsonify({"success": True, "message": f"Notification {doc_id} cleared."}), 200
        
    except Exception as e:
        print(f"❌ Delete notification error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# PUBLISH INTELLIGENCE UPDATE
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/publish-intel', methods=['POST'])
def publish_intel():
    """
    Creates a new intelligence channel update visible to all merchants.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    header = data.get('header')
    message = data.get('message')
    img_url = data.get('imgUrl')
    
    if not header or not message:
        return jsonify({"success": False, "error": "Missing header or message."}), 400
    
    try:
        ref = db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('intelligence_channel').add({
            "header": header,
            "message": message,
            "imgUrl": img_url,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "adminId": data.get('adminId')
        })
        
        print(f"📢 Intel published: {header} (ID: {ref[1].id})")
        return jsonify({"success": True, "docId": ref[1].id}), 200
        
    except Exception as e:
        print(f"❌ Intel publish error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# DELETE INTELLIGENCE UPDATE
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/delete-intel', methods=['POST'])
def delete_intel():
    """
    Removes an intelligence channel update.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    doc_id = data.get('docId')
    if not doc_id:
        return jsonify({"success": False, "error": "Missing docId."}), 400
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('intelligence_channel').document(doc_id).delete()
        
        print(f"✅ Intel deleted: {doc_id}")
        return jsonify({"success": True}), 200
        
    except Exception as e:
        print(f"❌ Intel delete error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# REMOVE ENDORSEMENT WAITLIST ENTRY
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/remove-waitlist', methods=['POST'])
def remove_waitlist():
    """
    Removes a merchant from the endorsement waitlist.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    doc_id = data.get('docId')
    if not doc_id:
        return jsonify({"success": False, "error": "Missing docId."}), 400
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('endorsement_waitlist').document(doc_id).delete()
        
        print(f"✅ Waitlist entry removed: {doc_id}")
        return jsonify({"success": True}), 200
        
    except Exception as e:
        print(f"❌ Waitlist removal error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# REVOKE ONBOARDING TOKEN
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/revoke-token', methods=['POST'])
def revoke_token():
    """
    Revokes an active onboarding token, preventing it from being used.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    token_id = data.get('tokenId')
    if not token_id:
        return jsonify({"success": False, "error": "Missing tokenId."}), 400
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('onboarding_tokens').document(token_id).update({
            "status": "revoked",
            "revokedAt": firestore.SERVER_TIMESTAMP,
            "revokedBy": data.get('adminId')
        })
        
        print(f"✅ Token revoked: {token_id[:8]}...")
        return jsonify({"success": True}), 200
        
    except Exception as e:
        print(f"❌ Token revoke error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# TOGGLE SECURITY CONFIGURATION
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/toggle-security', methods=['POST'])
def toggle_security():
    """
    Toggles the enforceTokens flag in the security_config document.
    When enabled, merchants must use an onboarding token to access the CMS.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    is_enabled = data.get('enabled', False)
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('security_config').document('onboarding').set({
            "enforceTokens": bool(is_enabled),
            "lastModified": firestore.SERVER_TIMESTAMP,
            "modifiedBy": data.get('adminId')
        })
        
        state = "enabled" if is_enabled else "disabled"
        print(f"🔒 Token enforcement {state} by {data.get('adminId')}")
        return jsonify({"success": True, "enforceTokens": is_enabled}), 200
        
    except Exception as e:
        print(f"❌ Security config error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# LEGACY TAKEDOWN (Preserved for backward compatibility)
# ═══════════════════════════════════════════════════════════════

@admin_bp.route('/api/admin/takedown', methods=['POST'])
def execute_takedown():
    """
    Legacy takedown endpoint. Adds a listing ID to the takedown_registry.
    Prefer /api/admin/takedown-listing for direct deletion.
    """
    data = request.json or {}
    if not validate_admin(data.get('adminId'), data.get('adminPin')):
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    listing_id = data.get('listingId')
    if not listing_id:
        return jsonify({"success": False, "error": "Missing listingId."}), 400

    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('takedown_registry').document(listing_id).set({
              "timestamp": firestore.SERVER_TIMESTAMP,
              "reason": data.get('reason', 'Institutional Safety Audit'),
              "active": True,
              "executed_by": data.get('adminId')
          })
        
        print(f"✅ Legacy takedown registered: {listing_id}")
        return jsonify({"success": True, "message": f"Listing {listing_id} neutralized."}), 200
        
    except Exception as e:
        print(f"❌ Legacy takedown error: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    
# ── APPROVE MOMO CHANGE ──
@admin_bp.route('/api/admin/approve-momo-change', methods=['POST'])
def approve_momo_change():
    data = request.json or {}
    session_token = data.get('sessionToken')
    admin_id = data.get('adminId')
    admin_pin = data.get('adminPin')
    
    # Support both session token and legacy PIN auth
    is_valid = False
    if session_token:
        valid, resolved_id = validate_admin_session(session_token)
        is_valid = valid
    elif admin_id and admin_pin:
        is_valid = validate_admin(admin_id, admin_pin)
    
    if not is_valid:
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    doc_id = data.get('docId')
    merchant_id = data.get('merchantId')
    new_momo = data.get('newMomo')
    
    if not doc_id or not merchant_id or not new_momo:
        return jsonify({"success": False, "error": "Missing parameters."}), 400
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('verified_merchants').document(merchant_id) \
          .update({'momo': new_momo})
        
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('momo_change_requests').document(doc_id) \
          .update({
              'status': 'approved',
              'reviewedBy': admin_id or resolved_id,
              'reviewedAt': firestore.SERVER_TIMESTAMP
          })
        
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── DENY MOMO CHANGE ──
@admin_bp.route('/api/admin/deny-momo-change', methods=['POST'])
def deny_momo_change():
    data = request.json or {}
    session_token = data.get('sessionToken')
    admin_id = data.get('adminId')
    admin_pin = data.get('adminPin')
    
    is_valid = False
    if session_token:
        valid, resolved_id = validate_admin_session(session_token)
        is_valid = valid
    elif admin_id and admin_pin:
        is_valid = validate_admin(admin_id, admin_pin)
    
    if not is_valid:
        return jsonify({"success": False, "error": "Unauthorized."}), 401
    
    doc_id = data.get('docId')
    if not doc_id:
        return jsonify({"success": False, "error": "Missing docId."}), 400
    
    try:
        db.collection('artifacts').document(APP_ID) \
          .collection('public').document('data') \
          .collection('momo_change_requests').document(doc_id) \
          .update({
              'status': 'denied',
              'reviewedBy': admin_id or resolved_id,
              'reviewedAt': firestore.SERVER_TIMESTAMP
          })
        
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500