from PIL import Image, ImageDraw, ImageFont
import os

def create_ledgehold_logo():
    # 1. Setup Canvas (High Resolution)
    size = (1000, 1000)
    background_color = (255, 255, 255)  # White background
    primary_color = (15, 23, 42)        # Slate 900 (Corporate Navy/Dark Slate)
    accent_color = (59, 130, 246)       # Blue 500 (Trust/Tech Blue)
    
    # Create image with transparency support (RGBA)
    img = Image.new('RGBA', size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # 2. Define Shield Geometry
    # We define the shield as a polygon with a pointed bottom
    center_x, center_y = 500, 400
    width, height = 400, 500
    
    shield_points = [
        (center_x - width//2, center_y - height//2), # Top Left
        (center_x + width//2, center_y - height//2), # Top Right
        (center_x + width//2, center_y + height//4), # Right Mid
        (center_x, center_y + height//2),            # Bottom Point
        (center_x - width//2, center_y + height//4), # Left Mid
    ]

    # 3. Create Sliced Shield Effect
    # We use a mask to draw the shield, then "cut" diagonal lines through it
    mask = Image.new('L', size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.polygon(shield_points, fill=255)

    # Create a temporary surface to draw the full shield
    shield_layer = Image.new('RGBA', size, (0, 0, 0, 0))
    shield_draw = ImageDraw.Draw(shield_layer)
    shield_draw.polygon(shield_points, fill=primary_color)

    # Define diagonal cutting lines (spaces between parts)
    # Line 1: Top-left to bottom-right
    # Line 2: Middle-left to middle-right
    line_width = 25
    cuts = [
        [(200, 200), (800, 600)],
        [(200, 450), (800, 250)]
    ]

    for line in cuts:
        shield_draw.line(line, fill=(0, 0, 0, 0), width=line_width)

    # Apply the mask to ensure the cuts only affect the shield shape
    final_shield = Image.composite(shield_layer, Image.new('RGBA', size, (0,0,0,0)), mask)
    img.paste(final_shield, (0, 0), final_shield)

    # 4. Add Typography
    try:
        # Standard system font paths
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        name_font = ImageFont.truetype(font_path, 85)
        sub_font = ImageFont.truetype(font_path, 45)
    except:
        name_font = ImageFont.load_default()
        sub_font = ImageFont.load_default()

    # Text rendering with slight shadow/depth for a premium feel
    draw.text((500, 820), "LEDGEHOLD", fill=primary_color, font=name_font, anchor="mm")
    draw.text((500, 900), "GHANA LTD", fill=(100, 116, 139), font=sub_font, anchor="mm")

    # 5. Save to static/images
    output_dir = os.path.join("static", "images")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output_path = os.path.join(output_dir, "ledgehold_logo.png")
    # Convert back to RGB for final save if you don't want transparency, 
    # or keep as PNG for transparency.
    final_img = Image.new("RGB", img.size, (255, 255, 255))
    final_img.paste(img, mask=img.split()[3]) 
    final_img.save(output_path)
    
    print(f"Shield logo successfully generated and saved to {output_path}")

if __name__ == "__main__":
    create_ledgehold_logo()