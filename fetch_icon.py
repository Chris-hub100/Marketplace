import requests
import shutil
import os

def download_favicon():
    # The direct link to the image you wanted (extracted from the Bing URL)
    image_url = "http://pluspng.com/img-png/wifi-png-wi-fi-icon-1600.png"
    
    # Where to save it
    save_folder = "static/images"
    if not os.path.exists(save_folder):
        os.makedirs(save_folder)
        
    save_path = os.path.join(save_folder, "favicon.png")

    print(f"⬇️ Downloading icon from: {image_url}...")

    # Download the image safely
    response = requests.get(image_url, stream=True)
    
    if response.status_code == 200:
        with open(save_path, 'wb') as out_file:
            shutil.copyfileobj(response.raw, out_file)
        print(f"✅ Success! Saved to: {save_path}")
        print("👉 Now restart your app and refresh the page.")
    else:
        print("❌ Failed to download. The link might be broken.")

if __name__ == "__main__":
    download_favicon()