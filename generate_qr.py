import qrcode
import os
from PIL import Image, ImageDraw
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

def create_badge_qr(url, filename):
    """
    Creates a 'Badge Style' QR: 
    - Rounded White Background (The Patch)
    - Gold Border (The Accent)
    - Black Rounded Dots (The Data - High Contrast)
    """
    
    # 1. Generate the inner QR Code (Just the dots)
    # We use minimal border here because we will add our own custom padding
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=20,
        border=0, 
    )
    qr.add_data(url)
    qr.make(fit=True)

    # Generate the image of the dots (Black dots, White background)
    qr_img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(), # Keeps the fabric-friendly rounded dots
    ).convert("RGBA")

    # 2. Create the Background "Badge"
    # We calculate a size that is larger than the QR code to create a "Quiet Zone"
    # and accommodate the rounded corners.
    
    padding = 70  # Space between QR dots and the gold border
    bg_width = qr_img.width + (padding * 2)
    bg_height = qr_img.height + (padding * 2)
    
    # Create a transparent canvas
    badge = Image.new("RGBA", (bg_width, bg_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    
    # 3. Draw the Rounded Rectangle (The White Patch with Gold Border)
    stroke_width = 20
    inset = stroke_width / 2 # Inset slightly so the border doesn't get clipped
    
    rect_coords = [
        (inset, inset), 
        (bg_width - inset, bg_height - inset)
    ]
    
    draw.rounded_rectangle(
        rect_coords, 
        radius=90,             # High radius for that smooth "Badge" look
        fill="white",          # White Background for High Contrast
        outline=(218, 165, 32), # Gold Color Accent
        width=stroke_width
    )
    
    # 4. Paste the QR Code in the center
    # Since qr_img has a white background, it will blend seamlessly with the white badge.
    badge.paste(qr_img, (padding, padding))

    # 5. Save
    save_folder = "static/images"
    if not os.path.exists(save_folder):
        os.makedirs(save_folder)
        
    save_path = os.path.join(save_folder, filename)
    badge.save(save_path)
    print(f"✅ Saved {filename} (Badge Style) -> Link: {url}")

if __name__ == "__main__":
    # ==========================================
    # GENERATE THE SHIRT ASSETS
    # ==========================================

    # 1. FRONT OF SHIRT ("Do Not Scan")
    create_badge_qr("https://dataexpress.store/?ref=front", "qr_front.png")
    
    # 2. BACK OF SHIRT ("Curiosity / Following")
    create_badge_qr("https://dataexpress.store/?ref=back", "qr_back.png")