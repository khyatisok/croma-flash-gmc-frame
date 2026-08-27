import os
import re
import json
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image
from lxml import etree

# =====================================================
# CONFIG
# =====================================================

CAMPAIGN_URL = "https://www.croma.com/campaign/24hrs-flash-sale-offers/c/7442"
GMC_FEED = "https://www.croma.com/gmcfeed.xml"

IMAGE_FOLDER = "images"
CACHE_FILE = "image_cache.json"

# Your GitHub Pages URL
IMAGE_BASE_URL = "https://khyatisok.github.io/croma-flash-gmc-frame/images"

# Final output image size
OUTPUT_SIZE = 1080

# Resize product to 75% of canvas
SCALE = 0.57

# Frame image
FRAME_PATH = "frame.png"

MAX_WORKERS = 6

# =====================================================

os.makedirs(IMAGE_FOLDER, exist_ok=True)

session = requests.Session()

# Load frame only once
frame = Image.open(FRAME_PATH).convert("RGBA")
frame = frame.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)

print("Downloading campaign page...")

html = session.get(CAMPAIGN_URL, timeout=30).text

skus = set(re.findall(r'"sku"\s*:\s*"(\d+)"', html))

print(f"Found {len(skus)} Flash Sale SKUs")

print("Downloading GMC feed...")

xml = session.get(GMC_FEED, timeout=60).content

root = etree.fromstring(xml)

ns = {
    "g": "http://base.google.com/ns/1.0"
}

channel = root.find("channel")
items = channel.findall("item")

# -----------------------------------------------------
# Load cache
# -----------------------------------------------------

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        cache = json.load(f)
else:
    cache = {}

new_cache = {}

tasks = []

# -----------------------------------------------------
# Filter products
# -----------------------------------------------------

for item in list(items):

    sku_node = item.find("g:id", ns)

    if sku_node is None:
        continue

    sku = sku_node.text.strip()

    image_node = item.find("g:image_link", ns)

    if image_node is None:
        continue

    image_url = image_node.text.strip()
    
    new_cache[sku] = image_url
    
    # -------------------------------------------------
    # Only modify EDLP products
    # -------------------------------------------------
    
    if sku in skus:
    
        # custom_label_3
        custom_label_3 = item.find("g:custom_label_3", ns)
    
        if custom_label_3 is not None:
            custom_label_3.text = "edlp"
    
        # internal_label after custom_label_4
        custom_label_4 = item.find("g:custom_label_4", ns)
    
        internal_label = etree.Element(
            "{http://base.google.com/ns/1.0}internal_label"
        )
    
        internal_label.text = "['edlp']"
    
        item.insert(
            list(item).index(custom_label_4) + 1,
            internal_label
        )
    
        # Replace image URLs
        new_url = f"{IMAGE_BASE_URL}/{sku}.png"
    
        image_node.text = new_url
    
        additional = item.find("g:additional_image_link", ns)
    
        if additional is not None:
            additional.text = new_url
    
        # Regenerate framed image only if needed
        image_path = os.path.join(
            IMAGE_FOLDER,
            f"{sku}.png"
        )
    
        if (
            sku not in cache
            or cache[sku] != image_url
            or not os.path.exists(image_path)
        ):
            tasks.append((sku, image_url))

print(f"Images needing regeneration: {len(tasks)}")

# -----------------------------------------------------
# Delete images for products no longer in EDLP
# -----------------------------------------------------

existing_images = {
    filename[:-4]
    for filename in os.listdir(IMAGE_FOLDER)
    if filename.endswith(".png")
}

for old_sku in existing_images - skus:

    try:
        os.remove(os.path.join(IMAGE_FOLDER, f"{old_sku}.png"))
        print(f"Deleted {old_sku}.png")
    except Exception as e:
        print(f"Couldn't delete {old_sku}.png: {e}")

# -----------------------------------------------------
# Image Processor
# -----------------------------------------------------

def process_image(task):

    sku, image_url = task

    try:

        print(f"Downloading {sku}")

        response = session.get(image_url, timeout=30)

        response.raise_for_status()

        img = Image.open(BytesIO(response.content)).convert("RGBA")

        # Original dimensions
        w, h = img.size

        # Resize while maintaining aspect ratio
        target_w = int(OUTPUT_SIZE * SCALE)
        target_h = int((h / w) * target_w)

        # Prevent image from exceeding safe area
        if target_h > OUTPUT_SIZE * SCALE:
            target_h = int(OUTPUT_SIZE * SCALE)
            target_w = int((w / h) * target_h)

        resized = img.resize(
            (target_w, target_h),
            Image.LANCZOS
        )

        # Create white background
        canvas = Image.new(
            "RGBA",
            (OUTPUT_SIZE, OUTPUT_SIZE),
            (255, 255, 255, 255)
        )

        # Center product
        x = (OUTPUT_SIZE - target_w) // 2
        y = (OUTPUT_SIZE - target_h) // 2

        canvas.paste(
            resized,
            (x, y),
            resized
        )

        # Overlay frame
        canvas.alpha_composite(frame)

        output = os.path.join(
            IMAGE_FOLDER,
            f"{sku}.png"
        )

        canvas.save(
            output,
            optimize=True
        )

        print(f"Saved {sku}")

    except Exception as e:
        print(f"{sku}: {e}")

# -----------------------------------------------------
# Parallel processing
# -----------------------------------------------------

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    list(executor.map(process_image, tasks))

# -----------------------------------------------------
# Save XML
# -----------------------------------------------------

tree = etree.ElementTree(root)

tree.write(
    "flash_sale_feed.xml",
    encoding="utf-8",
    xml_declaration=True,
    pretty_print=True
)

# -----------------------------------------------------
# Save cache
# -----------------------------------------------------

with open(CACHE_FILE, "w") as f:
    json.dump(
        new_cache,
        f,
        indent=2
    )

print("Saved image cache")

print("flash_sale_feed.xml generated successfully")

print("Done.")
