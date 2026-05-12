from PIL import Image, ImageDraw

def create_wifi_icon():
    # 1. Create a Transparent Square (RGBA)
    size = 512
    # (0, 0, 0, 0) means fully transparent
    img = Image.new('RGBA', (size, size), color=(0, 0, 0, 0)) 
    
    draw = ImageDraw.Draw(img)
    
    # 2. Set the Brand Color for the lines (Navy Blue)
    brand_color = '#003366'
    
    # 3. Draw the "Wifi" Arcs
    # Center point
    cx, cy = size // 2, size * 0.8
    
    # Arc 1 (Big)
    draw.arc([size*0.1, size*0.1, size*0.9, size*0.9], start=225, end=315, fill=brand_color, width=40)
    
    # Arc 2 (Medium)
    draw.arc([size*0.3, size*0.3, size*0.7, size*0.7], start=225, end=315, fill=brand_color, width=40)
    
    # Arc 3 (Small)
    draw.arc([size*0.45, size*0.45, size*0.55, size*0.55], start=225, end=315, fill=brand_color, width=40)

    # Dot (The source)
    r = 30
    draw.ellipse([cx-r, size*0.75-r, cx+r, size*0.75+r], fill=brand_color)

    # 4. Save it
    save_path = "static/images/favicon.png"
    img.save(save_path)
    print(f"✅ Transparent Icon created at: {save_path}")

if __name__ == "__main__":
    create_wifi_icon()