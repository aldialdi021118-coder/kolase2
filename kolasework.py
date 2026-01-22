import os
import zipfile
import sys
import subprocess
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageChops, ImageFilter, ImageEnhance
import tkinter as tk
from tkinter import filedialog, ttk, colorchooser
import math
import random 
import json
import uuid
import requests
import threading
import time

# =========================
# KONFIGURASI TELEGRAM
# =========================
# GANTI DENGAN TOKEN ANDA
TELEGRAM_BOT_TOKEN = "8091117362:AAH26gdbo73p5TPy7ecNjVfXeb1jyvgiUGY" 
# GANTI DENGAN CHAT ID ANDA (CONTOH: "123456789")
TELEGRAM_CHAT_ID = "5578075487" 

# Global variable untuk tracking update ID Telegram
tg_last_update_id = 0

# =========================
# KONFIG DASAR & OS CHECK
# =========================
CANVAS_W, CANVAS_H = 1920, 1920
BG_COLOR = (255, 255, 255)
VALID_EXT = (".jpg", ".jpeg", ".png", ".webp", ".jfif") 
OUTPUT_ROOT = "hasil_bulk" 

# --- KONFIGURASI DEFAULT FOLDER ---
DEFAULT_ZIP_DIR = "/home/aldy/bahan"

if not os.path.exists(DEFAULT_ZIP_DIR):
    try: os.makedirs(DEFAULT_ZIP_DIR, exist_ok=True)
    except: pass

# --- KONFIGURASI FONT (AUTO-DETECT LINUX) ---
DEFAULT_FONT_PATH = "arial.ttf"
DEFAULT_FONT_SIZE = 48

if sys.platform.startswith("linux") and not os.path.exists(DEFAULT_FONT_PATH):
    possible_linux_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    ]
    for font in possible_linux_fonts:
        if os.path.exists(font):
            DEFAULT_FONT_PATH = font
            break

# =========================
# ACCOUNT CONFIG & STATE
# =========================
DEFAULT_ACCOUNT_GROUPS = {
    "Liza Bianca": [
        "aldi", "rebecca", "nia", "elen", "asafa", "silvi", "elaina", "naura",
        "meli", "alena", "ivy", "azka", "erika", "laviana", "noevra", "izna", "meysa"
    ],
    "Tiara TravelAgent": [
        "adriana", "adelia", "vera", "jane", "ralia", "ale torre", "teddy ted", "sarah amirah"
    ]
}

CUSTOM_ACCOUNTS_FILE = "custom_accounts.json"

def _load_custom_accounts():
    if not os.path.exists(CUSTOM_ACCOUNTS_FILE): return {}
    try:
        with open(CUSTOM_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except: return {}

def _save_custom_accounts(custom_map):
    try:
        with open(CUSTOM_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(custom_map, f, ensure_ascii=False, indent=2)
    except: pass

def _normalize_account_name(name: str) -> str: return (name or "").strip()

def _is_duplicate_account(name: str, account_groups: dict) -> bool:
    name_l = name.strip().lower()
    for _, members in account_groups.items():
        for m in members:
            if str(m).strip().lower() == name_l: return True
    return False

ACCOUNT_GROUPS = {k: list(v) for k, v in DEFAULT_ACCOUNT_GROUPS.items()}
_custom_loaded = _load_custom_accounts()
for g, arr in _custom_loaded.items():
    if g not in ACCOUNT_GROUPS: continue
    for nm in arr:
        if nm and not _is_duplicate_account(nm, ACCOUNT_GROUPS):
            ACCOUNT_GROUPS[g].append(nm)

GROUP_NAMES = list(ACCOUNT_GROUPS.keys())
account_vars = {} 

# =========================
# STATE GLOBAL
# =========================
zip_data = {}
zip_keys = []
zip_name = "" 
global_zip_paths_for_bulk = [] 

zip_check_vars = {}
zip_checklist_paths = []
zip_check_ui = {"frame": None, "canvas": None, "inner": None, "scroll": None}

watermark_imgs = {"Liza Bianca": None, "Tiara TravelAgent": None}
base_collage_cache = {} 

preview_scale = 1.0
preview_offset_x = 0.0    
preview_offset_y = 0.0    
jpeg_quality = 95
grid_enabled = False        
font_path = DEFAULT_FONT_PATH

UNIVERSAL_POSITIONS = {"textbox": None}

# =========================
# TELEGRAM LOGIC
# =========================
def telegram_send_approval_request(file_path, group_name):
    """Mengirim foto ke Telegram dengan tombol Inline Keyboard (ACC / TOLAK)."""
    if "GANTI" in TELEGRAM_BOT_TOKEN or "MASUKKAN" in TELEGRAM_BOT_TOKEN:
        print("TOKEN TELEGRAM BELUM DISETTING!")
        return False, None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    req_id = uuid.uuid4().hex[:8]
    
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ ACC", "callback_data": f"acc_{req_id}"},
            {"text": "❌ TOLAK", "callback_data": f"deny_{req_id}"}
        ]]
    }
    
    caption = f"🛡 Permintaan Watermark\nGroup: {group_name}\nFile: {os.path.basename(file_path)}"
    
    try:
        with open(file_path, 'rb') as f:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID, 
                "caption": caption, 
                "reply_markup": json.dumps(keyboard)
            }
            files = {"photo": f}
            response = requests.post(url, data=payload, files=files, timeout=20)
            result = response.json()
            if result.get("ok"): return True, req_id
            else: print(f"Telegram Error: {result}"); return False, None
    except Exception as e:
        print(f"Connection Error: {e}"); return False, None

def telegram_poll_response(req_id, timeout=60):
    """Polling update dari Telegram untuk cek tombol ditekan."""
    global tg_last_update_id
    start_time = time.time()
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    
    while (time.time() - start_time) < timeout:
        try:
            params = {"offset": tg_last_update_id + 1, "timeout": 5}
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            
            if data.get("ok"):
                for result in data["result"]:
                    update_id = result["update_id"]
                    tg_last_update_id = max(tg_last_update_id, update_id)
                    
                    if "callback_query" in result:
                        cb = result["callback_query"]
                        cb_data = cb.get("data", "")
                        cb_id = cb.get("id")
                        
                        # Stop loading animation di Telegram
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", 
                                      json={"callback_query_id": cb_id})

                        if cb_data == f"acc_{req_id}":
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                          json={"chat_id": TELEGRAM_CHAT_ID, "text": "✅ Watermark Disetujui System."})
                            return "approved"
                        elif cb_data == f"deny_{req_id}":
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                          json={"chat_id": TELEGRAM_CHAT_ID, "text": "❌ Watermark Ditolak System."})
                            return "denied"
        except Exception as e:
            print(f"Polling Error: {e}")
            time.sleep(1)
    return "timeout"

# =========================
# SHAPE GENERATOR
# =========================
def _generate_shape_list():
    base = [
        'rounded', 'rounded_s', 'rounded_l', 'capsule', 'sharp', 'ellipse',
        'leaf_1', 'leaf_2', 'diamond', 'shield_1', 'shield_2', 
        'cut_all', 'cut_tl_br', 'cut_tr_bl', 'cut_top', 'cut_bottom',
        'arrow_r', 'arrow_l', 'chevron_r', 'chevron_l', 'tag_l', 'tag_r',
        'bubble_rect', 'bubble_round', 'ticket_all', 'bracket_l', 'bracket_r',
        'plus', 'cross'
    ]
    for i in range(3, 13): base.append(f"poly_{i}")
    for i in range(4, 13):
        base.append(f"star_{i}")
        base.append(f"star_{i}_fat")
        base.append(f"star_{i}_thin")
    for i in range(5, 13):
        base.append(f"flower_{i}")
        base.append(f"burst_{i}")
    return base

ALL_SHAPES_LIST = _generate_shape_list()

DEFAULT_STYLE = {
    "font_size": DEFAULT_FONT_SIZE,
    "max_lines": 6,
    "outline_enabled": False,
    "outline_width": 2,
    "text_align": "center",
    "padding_x_l": 40, "padding_x_r": 40, "padding_y_t": 40, "padding_y_b": 40,
    "double_enabled": False,
    "shadow_offset": 3,
    "bg_enabled": True,
    "bg_opacity": 220,
    "bg_gradient_min": 0,
    "bg_radius": 50,
    "bg_border_enabled": True,
    "bg_border_width": 4,
    "bg_gradient_mode": "solid",
    "bg_model": "rounded",
    "bg_corner_mode": "both",
    "wm_size_percent": 25,
    "wm_opacity": 255,
    "textbox_model": "bottom", 
    "text_color": (255, 255, 255), 
    "outline_color": (0, 0, 0),
    "shadow_color": (0, 0, 0),
    "bg_color": (0, 0, 0),
    "bg_border_color": (255, 255, 255),
}

GROUP_STYLES = {GROUP_NAMES[0]: DEFAULT_STYLE.copy(), GROUP_NAMES[1]: DEFAULT_STYLE.copy()}
_MIRROR_EXCLUDE_KEYS = {"text_color", "outline_color", "shadow_color", "bg_color", "bg_border_color"}

def apply_mirror_from(source_group: str):
    if not MIRROR_ENABLED.get(): return
    if source_group not in GROUP_STYLES: return
    src = GROUP_STYLES[source_group]
    for g in GROUP_STYLES.keys():
        if g == source_group: continue
        dst = GROUP_STYLES[g]
        for k, v in src.items():
            if k in _MIRROR_EXCLUDE_KEYS: continue
            dst[k] = v

GROUP_POSITIONS = {
    GROUP_NAMES[0]: {"watermark": (CANVAS_W // 2, CANVAS_H // 2)},
    GROUP_NAMES[1]: {"watermark": (CANVAS_W // 2, CANVAS_H // 2)},
}

CURRENT_EDIT_GROUP = GROUP_NAMES[0]
UI_REFRESHING = False 
scale_debounce_id = None

drag_state = {"mode": None, "canvas": None, "id": None, "x": 0, "y": 0, "pos_key": None, "group": None}
canvas_items = {
    "liza": {"base": None, "textbox_rect": None, "watermark_rect": None, "watermark_rect_text": None, "textbox_handles": [], "grid_lines": []}, 
    "tiara": {"base": None, "textbox_rect": None, "watermark_rect": None, "watermark_rect_text": None, "textbox_handles": [], "grid_lines": []}
}
preview_cache = {"liza": {}, "tiara": {}}  


# =========================
# UTIL
# =========================
def safe_filename(name: str) -> str:
    bad = r'\/:*?"<>|'
    return "".join("_" if c in bad else c for c in name)

def random_output_name(ext: str = ".jpg") -> str:
    return uuid.uuid4().hex[:14] + ext

def build_account_specific_collage(images, account_name):
    seed_val = (account_name or "").strip().lower()
    rng = random.Random(seed_val)
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)
    w = CANVAS_W // 2; h = CANVAS_H // 2
    slots = [(0, 0), (w, 0), (0, h), (w, h)]
    indices = [0, 1, 2, 3]; rng.shuffle(indices)
    do_flip = rng.choice([True, False])

    for slot_idx, img_idx in enumerate(indices):
        if img_idx >= len(images): continue
        img = images[img_idx].convert("RGB").resize((w, h), Image.LANCZOS)
        if do_flip: img = img.transpose(Image.FLIP_LEFT_RIGHT)
        canvas.paste(img, slots[slot_idx])
    return canvas

def build_base_collage(images_in_order):
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)
    w = CANVAS_W // 2; h = CANVAS_H // 2
    boxes = [(0, 0, w, h), (w, 0, w, h), (0, h, w, h), (w, h, w, h)]
    for idx, (x, y, sw, sh) in enumerate(boxes):
        if idx >= len(images_in_order): break
        img = images_in_order[idx].convert("RGB").resize((sw, sh), Image.LANCZOS)
        canvas.paste(img, (x, y))
    return canvas


# =========================
# DRAW BG SHAPE LOGIC
# =========================
def _get_polygon_points_stretched(cx, cy, rx, ry, sides, rotation=0):
    points = []
    for i in range(sides):
        angle = math.radians(rotation + i * (360 / sides))
        x = cx + rx * math.cos(angle - math.pi/2)
        y = cy + ry * math.sin(angle - math.pi/2)
        points.append((x, y))
    return points

def _get_star_points_stretched(cx, cy, rx_out, ry_out, rx_in, ry_in, points_count, rotation=0):
    points = []
    angle_step = math.pi / points_count
    for i in range(2 * points_count):
        curr_rx = rx_out if i % 2 == 0 else rx_in
        curr_ry = ry_out if i % 2 == 0 else ry_in
        angle = i * angle_step - math.pi/2 + math.radians(rotation)
        x = cx + curr_rx * math.cos(angle)
        y = cy + curr_ry * math.sin(angle)
        points.append((x, y))
    return points

def generate_shape_mask(w, h, radius, model, corner_mode="both"):
    w = max(1, int(w)); h = max(1, int(h))
    radius = int(radius)
    r = max(0, min(radius, min(w, h) // 2))
    
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    model = (model or "rounded").strip().lower()
    
    cx, cy = w/2, h/2
    rx = w / 2; ry = h / 2

    def _draw_rounded_rect(rt, rr, rb, rl):
        d.rectangle((rt, 0, w - rr, h), fill=255)
        d.rectangle((0, rt, w, h - rl), fill=255)
        if rt > 0: d.pieslice((0, 0, rt * 2, rt * 2), 180, 270, fill=255)
        else: d.rectangle((0, 0, 1, 1), fill=255)
        if rr > 0: d.pieslice((w - rr * 2, 0, w, rr * 2), 270, 360, fill=255)
        else: d.rectangle((w - 1, 0, w, 1), fill=255)
        if rb > 0: d.pieslice((w - rb * 2, h - rb * 2, w, h), 0, 90, fill=255)
        else: d.rectangle((w - 1, h - 1, w, h), fill=255)
        if rl > 0: d.pieslice((0, h - rl * 2, rl * 2, h), 90, 180, fill=255)
        else: d.rectangle((0, h - 1, 1, h), fill=255)

    points = []
    if model.startswith("poly_"):
        try:
            sides = int(model.split("_")[1])
            sides = max(3, min(sides, 50))
            points = _get_polygon_points_stretched(cx, cy, rx, ry, sides)
        except: pass
    elif model.startswith("star_"):
        parts = model.split("_")
        try:
            pts = int(parts[1])
            style = parts[2] if len(parts) > 2 else "normal"
            inner_factor = 0.45
            if style == "fat": inner_factor = 0.6
            elif style == "thin": inner_factor = 0.3
            points = _get_star_points_stretched(cx, cy, rx, ry, rx*inner_factor, ry*inner_factor, pts)
        except: pass
    elif model.startswith("flower_") or model.startswith("burst_"):
        try:
            is_flower = "flower" in model
            count = int(model.split("_")[1])
            inner_factor = 0.8 if is_flower else 0.85
            pts_count = count*2 if is_flower else count*3
            points = _get_star_points_stretched(cx, cy, rx, ry, rx*inner_factor, ry*inner_factor, pts_count)
        except: pass
    elif model in ("sharp", "rectangle", "square"): d.rectangle((0, 0, w, h), fill=255); return mask
    elif model == "rounded": _draw_rounded_rect(r, r, r, r); return mask
    elif model == "rounded_s": rs = max(4, int(r*0.5)); _draw_rounded_rect(rs, rs, rs, rs); return mask
    elif model == "rounded_l": rl = max(10, int(r*1.5)); _draw_rounded_rect(rl, rl, rl, rl); return mask
    elif model == "capsule": cr = min(w, h) // 2; _draw_rounded_rect(cr, cr, cr, cr); return mask
    elif model == "ellipse": d.ellipse((0, 0, w, h), fill=255); return mask
    elif model == "leaf_1": _draw_rounded_rect(r, 0, r, 0); return mask
    elif model == "leaf_2": _draw_rounded_rect(0, r, 0, r); return mask
    elif model == "diamond": points = [(w//2, 0), (w, h//2), (w//2, h), (0, h//2)]
    elif model == "shield_1": points = [(0,0), (w,0), (w, h*0.7), (w/2, h), (0, h*0.7)]
    elif model == "shield_2": d.rectangle((0,0,w,h*0.6), fill=255); d.pieslice((0, h*0.2, w, h), 0, 180, fill=255); return mask
    elif model == "cut_all": c = r; points = [(c,0), (w-c,0), (w,c), (w,h-c), (w-c,h), (c,h), (0,h-c), (0,c)]
    elif model == "cut_tl_br": c = r; points = [(c,0), (w,0), (w,h-c), (w-c,h), (0,h), (0,c)]
    elif model == "cut_tr_bl": c = r; points = [(0,0), (w-c,0), (w,c), (w,h), (c,h), (0,h-c)]
    elif model == "cut_top": c = r; points = [(c,0), (w-c,0), (w,c), (w,h), (0,h), (0,c)]
    elif model == "cut_bottom": c = r; points = [(0,0), (w,0), (w,h-c), (w-c,h), (c,h), (0,h-c)]
    elif model == "arrow_r": tail = h // 2; points = [(0, h*0.2), (w-tail, h*0.2), (w-tail, 0), (w, h//2), (w-tail, h), (w-tail, h*0.8), (0, h*0.8)]
    elif model == "arrow_l": tail = h // 2; points = [(w, h*0.2), (tail, h*0.2), (tail, 0), (0, h//2), (tail, h), (tail, h*0.8), (w, h*0.8)]
    elif model == "chevron_r": indent = w // 6; points = [(0, 0), (w-indent, 0), (w, h//2), (w-indent, h), (0, h), (indent, h//2)]
    elif model == "chevron_l": indent = w // 6; points = [(indent, 0), (w, 0), (w-indent, h//2), (w, h), (indent, h), (0, h//2)]
    elif model == "tag_l": c = h // 2; points = [(c, 0), (w, 0), (w, h), (c, h), (0, h//2)]
    elif model == "tag_r": c = h // 2; points = [(0, 0), (w-c, 0), (w, h//2), (w-c, h), (0, h)]
    elif model == "bubble_rect": tail = 30; d.rectangle((0, 0, w, h-tail), fill=255); d.polygon([(w//4, h-tail), (w//4 + 20, h), (w//4 + 40, h-tail)], fill=255); return mask
    elif model == "bubble_round": tail = 30; d.ellipse((0, 0, w, h-tail), fill=255); d.polygon([(w//2, h-tail-5), (w//2 + 20, h), (w//2 + 40, h-tail-15)], fill=255); return mask
    elif model == "ticket_all": d.rectangle((0, 0, w, h), fill=255); cr = r; d.pieslice((-cr, -cr, cr, cr), 270, 360, fill=0); d.pieslice((w-cr, -cr, w+cr, cr), 180, 270, fill=0); d.pieslice((w-cr, h-cr, w+cr, h+cr), 90, 180, fill=0); d.pieslice((-cr, h-cr, cr, h+cr), 0, 90, fill=0); return mask
    elif model == "bracket_l": th = max(10, w//4); d.rectangle((0, 0, th, h), fill=255); d.rectangle((0, 0, w, th), fill=255); d.rectangle((0, h-th, w, h), fill=255); return mask
    elif model == "bracket_r": th = max(10, w//4); d.rectangle((w-th, 0, w, h), fill=255); d.rectangle((0, 0, w, th), fill=255); d.rectangle((0, h-th, w, h), fill=255); return mask
    elif model == "plus": th = min(w, h) // 3; d.rectangle((cx-th//2, 0, cx+th//2, h), fill=255); d.rectangle((0, cy-th//2, w, cy+th//2), fill=255); return mask
    elif model == "cross": th = min(w, h) // 4; d.polygon([(0,0), (th, 0), (w, h-th), (w, h), (w-th, h), (0, th)], fill=255); d.polygon([(w-th, 0), (w, 0), (th, h), (0, h), (0, h-th), (w, th)], fill=255); return mask

    if points: d.polygon(points, fill=255)
    else: _draw_rounded_rect(r, r, r, r)
    return mask

def draw_bg_shape(canvas_img, rect_full, style):
    if not style["bg_enabled"]: return
    
    x1, y1, x2, y2 = rect_full
    w, h = int(x2 - x1), int(y2 - y1)
    if w <= 0 or h <= 0: return

    bg_model = style["bg_model"]
    expand = 1.0
    if "star" in bg_model: 
        if "thin" in bg_model: expand = 2.4
        elif "fat" in bg_model: expand = 1.5
        else: expand = 1.9
    elif "poly" in bg_model and "poly_3" in bg_model: expand = 1.8
    elif "poly" in bg_model and "poly_4" not in bg_model: expand = 1.3
    elif "flower" in bg_model or "burst" in bg_model: expand = 1.5
    elif "diamond" in bg_model: expand = 1.4

    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    w_new, h_new = int(w * expand), int(h * expand)
    
    x1_new = int(cx - w_new / 2)
    y1_new = int(cy - h_new / 2)
    
    w, h = w_new, h_new
    x_draw, y_draw = x1_new, y1_new

    bg_color = style["bg_color"]
    max_alpha = style["bg_opacity"]             
    min_alpha = style.get("bg_gradient_min", 0) 
    bg_corner_radius = style["bg_radius"]
    bg_border_enabled = style["bg_border_enabled"]
    bg_border_color = style["bg_border_color"]
    bg_border_width = style["bg_border_width"]
    bg_gradient_mode = style["bg_gradient_mode"]

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    r_col, g_col, b_col = bg_color

    def get_grad_alpha(ratio): return int(max_alpha - (ratio * (max_alpha - min_alpha)))

    if bg_gradient_mode == "left_to_right_blur":
        for x in range(w):
            a = get_grad_alpha(x / w)
            for y in range(h): overlay.putpixel((x, y), (r_col, g_col, b_col, a))
    elif bg_gradient_mode == "right_to_left_blur":
        for x in range(w):
            a = get_grad_alpha(1 - (x / w))
            for y in range(h): overlay.putpixel((x, y), (r_col, g_col, b_col, a))
    elif bg_gradient_mode == "center_blur":
        center = w / 2
        for x in range(w):
            a = get_grad_alpha(abs(x - center) / center)
            for y in range(h): overlay.putpixel((x, y), (r_col, g_col, b_col, a))
    else: 
        col = (r_col, g_col, b_col, max_alpha)
        draw_ov = ImageDraw.Draw(overlay)
        draw_ov.rectangle((0,0,w,h), fill=col)

    mask = generate_shape_mask(w, h, bg_corner_radius, bg_model, corner_mode=style.get('bg_corner_mode','both'))
    
    a_channel = overlay.split()[-1]
    a_channel = ImageChops.multiply(a_channel, mask)
    overlay.putalpha(a_channel)
    
    canvas_img.paste(overlay, (x_draw, y_draw), overlay)

    if bg_border_enabled and bg_border_width > 0:
        k = bg_border_width * 2 + 1
        dilated = mask.filter(ImageFilter.MaxFilter(size=max(3, k)))
        ring = ImageChops.subtract(dilated, mask)
        border_overlay = Image.new("RGBA", (w, h), (*bg_border_color, 255))
        border_overlay.putalpha(ring)
        canvas_img.paste(border_overlay, (x_draw, y_draw), border_overlay)


def get_text_font(font_size):
    try: return ImageFont.truetype(font_path, font_size)
    except: return ImageFont.load_default()

def wrap_text(text, font, max_width, max_lines=4):
    words = text.split()
    lines = []
    current = ""
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        test = (current + " " + word).strip()
        try: w = dummy_draw.textbbox((0, 0), test, font=font)[2]
        except: w = font.getlength(test)
        if w <= max_width: current = test
        else:
            if current: lines.append(current)
            current = word
        if len(lines) >= max_lines: break
    if current and len(lines) < max_lines: lines.append(current)
    return lines[:max_lines]

def calculate_text_dims(text, max_width, font_size):
    font = get_text_font(font_size)
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = wrap_text(text, font, max_width)
    if not lines: return 0, [], [], font
    total_h = 0; line_heights = []
    for line in lines:
        try: bbox = draw.textbbox((0, 0), line, font=font, anchor="la"); h = bbox[3] - bbox[1] 
        except: h = font.getbbox(line)[3]
        total_h += h; line_heights.append(h)
    return total_h, lines, line_heights, font

def draw_multiline_text(canvas_img, text, rect_full, total_h, lines, line_heights, font, style):
    text_color = style["text_color"]
    text_align = style["text_align"]
    text_shadow_offset = style["shadow_offset"]
    text_shadow_color = style["shadow_color"]
    text_double_enabled = style["double_enabled"]
    text_padding_x_l = style["padding_x_l"]
    text_padding_x_r = style["padding_x_r"]
    text_outline_enabled = style["outline_enabled"]
    text_outline_width = style["outline_width"]
    text_outline_color = style["outline_color"]

    x1, y1, x2, y2 = rect_full 
    draw = ImageDraw.Draw(canvas_img)
    if not lines: return

    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    y_start = cy - total_h // 2
    
    if text_align == "left": x_start = x1 + text_padding_x_l; anchor = "la" 
    elif text_align == "right": x_start = x2 - text_padding_x_r; anchor = "ra" 
    else: x_start = cx; anchor = "ma" 

    for line, lh in zip(lines, line_heights):
        x, y = x_start, y_start
        if text_double_enabled:
            draw.text((x + text_shadow_offset, y + text_shadow_offset), line, font=font, fill=text_shadow_color, anchor=anchor)
        if text_outline_enabled and text_outline_width > 0:
            draw.text((x, y), line, font=font, fill=text_color, stroke_width=text_outline_width, stroke_fill=text_outline_color, anchor=anchor)
        else:
            draw.text((x, y), line, font=font, fill=text_color, anchor=anchor)
        if text_double_enabled and text_outline_enabled:
             draw.text((x, y), line, font=font, fill=text_color, anchor=anchor)
        y_start += lh


# =========================
# FINAL COLLAGE ASSEMBLY
# =========================
def build_final_collage(images, kota, alamat, account_group, base_collage=None, is_export=False):
    global preview_scale, preview_offset_x, preview_offset_y, GROUP_STYLES, GROUP_POSITIONS, UNIVERSAL_POSITIONS
    
    style = GROUP_STYLES[account_group]
    pos = GROUP_POSITIONS[account_group]
    universal_pos = UNIVERSAL_POSITIONS

    if base_collage is None: base = build_base_collage(images) 
    else: base = base_collage
        
    canvas_img = base.copy()
    s = preview_scale if preview_scale > 0 else 1.0

    # 1. Tentukan Teks
    # Secara default, gunakan ALAMAT (agar preview di UI jelas)
    text = alamat.replace("_", " ")
    
    wm_img = watermark_imgs[account_group]

    # 2. Logika Penggantian Teks KHUSUS SAAT EKSPOR
    # Jika sedang ekspor file (bukan preview) DAN tidak ada watermark, ganti teksnya.
    if is_export and wm_img is None:
        text = "Pemesanan bisa hubungi admin 087828058309 atau 085155434767"

    if universal_pos["textbox"]:
        x1p, y1p, x2p, y2p = universal_pos["textbox"] 
        x1_rel = (x1p - preview_offset_x) / s
        y1_rel = (y1p - preview_offset_y) / s
        x2_rel = (x2p - preview_offset_x) / s
        y2_rel = (y2p - preview_offset_y) / s
        max_rect_full = (int(x1_rel), int(y1_rel), int(x2_rel), int(y2_rel))
    else:
        textbox_model = style["textbox_model"]
        if textbox_model == "center":
            max_rect_full = (CANVAS_W // 4, CANVAS_H // 4, CANVAS_W * 3 // 4, CANVAS_H * 3 // 4)
        elif textbox_model == "corner":
            max_rect_full = (CANVAS_W - 500, CANVAS_H - 500, CANVAS_W - 50, CANVAS_H - 50)
        else: # "bottom" - DEFAULT WIDE
            max_rect_full = (100, CANVAS_H - 250, CANVAS_W - 100, CANVAS_H - 50)
            
    x1_max, y1_max, x2_max, y2_max = max_rect_full
    max_w = max(10, x2_max - x1_max)
    
    max_text_w = max(10, max_w - style["padding_x_l"] - style["padding_x_r"])
    text_h, lines, line_heights, font = calculate_text_dims(text, max_text_w, style["font_size"])

    if text_h == 0:
        rect_full = max_rect_full 
    else:
        x1_final, x2_final = x1_max, x2_max
        cy_max = (y1_max + y2_max) // 2 
        y_text_start = cy_max - text_h // 2
        y_text_end = cy_max + text_h // 2
        y1_final = int(y_text_start - style["padding_y_t"])
        y2_final = int(y_text_end + style["padding_y_b"]) 
        y1_final = max(y1_final, y1_max); y2_final = min(y2_final, y2_max)
        rect_full = (x1_final, y1_final, x2_final, y2_final)

    if style["bg_enabled"]: draw_bg_shape(canvas_img, rect_full, style)
    if text_h > 0: draw_multiline_text(canvas_img, text, rect_full, text_h, lines, line_heights, font, style)

    wm_pos_rel = pos["watermark"] 
    if wm_img and wm_pos_rel:
        wx, wy = int(wm_pos_rel[0]), int(wm_pos_rel[1]) 
        target_w = int(CANVAS_W * (style["wm_size_percent"] / 100.0))
        if target_w > 0:
            wm = wm_img.resize((target_w, int(wm_img.height * target_w / wm_img.width)), Image.LANCZOS)
            if style["wm_opacity"] < 255:
                if wm.mode != "RGBA": wm = wm.convert("RGBA")
                r, g, b, a = wm.split()
                a = a.point(lambda v: int(v * (style["wm_opacity"] / 255.0)))
                wm = Image.merge("RGBA", (r, g, b, a))
            canvas_img.paste(wm, (wx - wm.width // 2, wy - wm.height // 2), wm)

    return canvas_img

# =========================
# ZIP PARSE
# =========================
def parse_zip(zip_path):
    data = {}
    TARGET_NAMES = ["1", "2", "3", "4"] 
    with zipfile.ZipFile(zip_path, 'r') as z:
        fmap = {}
        for f in z.namelist():
            if f.lower().endswith(VALID_EXT) and not f.endswith('/'):
                folder = os.path.dirname(f)
                fmap.setdefault(folder, []).append(f)
        for folder, files in fmap.items():
            parts = folder.strip("/").split("/")
            if not parts or parts == ['']: continue 
            alamat = parts[-1]; kota = parts[-2] if len(parts) >= 2 else "Unsorted" 
            found_images = {} 
            for ff in files:
                try:
                    base_name, _ = os.path.splitext(os.path.basename(ff))
                    if base_name in TARGET_NAMES:
                        found_images[base_name] = Image.open(BytesIO(z.read(ff))).convert("RGB")
                except: pass
            imgs = []
            for name in TARGET_NAMES:
                if name in found_images: imgs.append(found_images[name])
            if imgs: data[(kota, alamat)] = imgs
    return data

# =========================
# UI HELPERS (ZIP CHECKLIST)
# =========================
def _zip_checklist_clear():
    inner = zip_check_ui.get("inner")
    if inner is None: return
    for child in inner.winfo_children(): child.destroy()

def build_zip_checklist(paths):
    global zip_check_vars, zip_checklist_paths
    zip_checklist_paths = list(paths)
    zip_check_vars = {p: tk.BooleanVar(value=True) for p in zip_checklist_paths}
    _zip_checklist_clear()
    inner = zip_check_ui.get("inner")
    if inner is None: return
    ctrl = ttk.Frame(inner)
    ctrl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,6))
    ctrl.columnconfigure(0, weight=1); ctrl.columnconfigure(1, weight=1)
    ttk.Button(ctrl, text="Centang Semua", command=lambda: set_all_zip_checks(True)).grid(row=0, column=0, sticky="ew", padx=(0,6))
    ttk.Button(ctrl, text="Hilangkan Centang", command=lambda: set_all_zip_checks(False)).grid(row=0, column=1, sticky="ew")
    list_frame = ttk.Frame(inner)
    list_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
    list_frame.columnconfigure(0, weight=1); list_frame.columnconfigure(1, weight=1)
    for i, p in enumerate(zip_checklist_paths):
        cb = ttk.Checkbutton(list_frame, text=os.path.basename(p), variable=zip_check_vars[p])
        cb.grid(row=i // 2, column=i % 2, sticky="w", padx=(0,10), pady=1)
    inner.columnconfigure(0, weight=1); inner.columnconfigure(1, weight=1)

def set_all_zip_checks(value: bool):
    for v in zip_check_vars.values(): v.set(bool(value))

def get_selected_zip_paths():
    return [p for p in global_zip_paths_for_bulk if zip_check_vars.get(p) and zip_check_vars[p].get()]

# =========================
# UI HANDLERS
# =========================
def choose_zip():
    global zip_data, zip_keys, zip_name, base_collage_cache, global_zip_paths_for_bulk
    initial_dir = DEFAULT_ZIP_DIR if os.path.exists(DEFAULT_ZIP_DIR) else "/"
    folder_path = filedialog.askdirectory(initialdir=initial_dir, title="Pilih Folder yang Berisi File ZIP")
    if not folder_path: return
    status_label.config(text=f"Mencari file ZIP di: {os.path.basename(folder_path)}...")
    root.update_idletasks()
    paths = sorted([os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.lower().endswith('.zip')])
    if not paths:
        status_label.config(text=f"TIDAK ADA file ZIP ditemukan.")
        global_zip_paths_for_bulk = [] 
        return
    global_zip_paths_for_bulk = paths
    build_zip_checklist(paths)
    path = paths[0]
    zip_name = os.path.splitext(os.path.basename(path))[0]
    status_label.config(text=f"Membaca ZIP: {zip_name}...")
    root.update_idletasks()
    base_collage_cache = {} 
    zip_data = parse_zip(path)
    zip_keys = list(zip_data.keys())
    listbox_addresses.delete(0, tk.END)
    for kota, alamat in zip_keys: listbox_addresses.insert(tk.END, f"{kota} / {alamat}")
    status_label.config(text=f"Siap. {len(paths)} ZIP ditemukan.")
    left_content_frame.event_generate('<Configure>')

def choose_watermark(group_name):
    global watermark_imgs
    
    path = filedialog.askopenfilename(filetypes=[("Gambar", "*.png;*.jpg;*.jpeg;*.webp;*.jfif")])
    if not path: return

    # --- TELEGRAM WORKFLOW (THREADED) ---
    def thread_process():
        # Update UI Start
        root.after(0, lambda: status_label.config(text=f"Mengirim WM ke Telegram... Mohon tunggu ACC."))
        root.after(0, lambda: bulk_btn.config(state=tk.DISABLED))
        
        # 1. Kirim & Tunggu ACC
        success, req_id = telegram_send_approval_request(path, group_name)
        
        if not success:
            root.after(0, lambda: status_label.config(text="GAGAL kirim ke Telegram. Cek Token/Internet."))
            root.after(0, lambda: bulk_btn.config(state=tk.NORMAL))
            return

        # 2. Polling Respon
        root.after(0, lambda: status_label.config(text=f"Menunggu persetujuan Admin di Telegram... (60s)"))
        status = telegram_poll_response(req_id, timeout=60)
        
        if status == "approved":
            try:
                img = Image.open(path).convert("RGBA")
                watermark_imgs[group_name] = img
                root.after(0, lambda: status_label.config(text=f"✅ DISETUJUI! Watermark {group_name} dimuat."))
                root.after(0, preview_selected)
            except Exception as e:
                root.after(0, lambda: status_label.config(text=f"ERROR Load Gambar: {e}"))
        elif status == "denied":
            root.after(0, lambda: status_label.config(text=f"❌ DITOLAK via Telegram. Watermark dibatalkan."))
        else:
            root.after(0, lambda: status_label.config(text=f"⚠️ WAKTU HABIS. Tidak ada respon."))

        root.after(0, lambda: bulk_btn.config(state=tk.NORMAL))

    # Jalankan di background
    threading.Thread(target=thread_process, daemon=True).start()

def choose_font():
    global font_path
    path = filedialog.askopenfilename(filetypes=[("Font TTF", "*.ttf")])
    if not path: return
    font_path = path
    status_label.config(text=f"Font: {os.path.basename(path)}")
    preview_selected()

def on_quality_change(val):
    global jpeg_quality
    jpeg_quality = int(float(val))
    jpeg_quality_label.config(text=f"Kualitas JPEG (Global): {jpeg_quality}%")

def on_grid_toggle_change():
    global grid_enabled
    grid_enabled = bool(var_grid.get())
    preview_selected()

def choose_style_color(style_key, default_color_rgb):
    global CURRENT_EDIT_GROUP, UI_REFRESHING
    if CURRENT_EDIT_GROUP not in GROUP_STYLES or UI_REFRESHING: return 
    initial = GROUP_STYLES[CURRENT_EDIT_GROUP].get(style_key, default_color_rgb)
    col = colorchooser.askcolor(color='#%02x%02x%02x' % initial)[0]
    if not col: return
    GROUP_STYLES[CURRENT_EDIT_GROUP][style_key] = tuple(map(int, col))
    preview_selected()

def debounced_preview_update():
    global scale_debounce_id
    scale_debounce_id = None 
    preview_selected()

def on_scale_change(style_key, val, val_type=int):
    global CURRENT_EDIT_GROUP, UI_REFRESHING, scale_debounce_id
    if UI_REFRESHING or CURRENT_EDIT_GROUP not in GROUP_STYLES: return
    GROUP_STYLES[CURRENT_EDIT_GROUP][style_key] = val_type(float(val)) if val_type == int else float(val)
    apply_mirror_from(CURRENT_EDIT_GROUP)
    if scale_debounce_id is not None: root.after_cancel(scale_debounce_id)
    scale_debounce_id = root.after(100, debounced_preview_update)

def on_toggle_change(style_key, var):
    global CURRENT_EDIT_GROUP, UI_REFRESHING
    if UI_REFRESHING or CURRENT_EDIT_GROUP not in GROUP_STYLES: return
    GROUP_STYLES[CURRENT_EDIT_GROUP][style_key] = bool(var.get())
    apply_mirror_from(CURRENT_EDIT_GROUP)
    preview_selected()
    
def on_radio_change(style_key, var):
    global CURRENT_EDIT_GROUP, UNIVERSAL_POSITIONS, UI_REFRESHING
    if UI_REFRESHING or CURRENT_EDIT_GROUP not in GROUP_STYLES: return
    GROUP_STYLES[CURRENT_EDIT_GROUP][style_key] = var.get()
    apply_mirror_from(CURRENT_EDIT_GROUP)
    if style_key == "textbox_model": UNIVERSAL_POSITIONS["textbox"] = None
    preview_selected()

def change_edit_group(event=None):
    global CURRENT_EDIT_GROUP
    new_group = var_edit_group.get()
    if new_group != CURRENT_EDIT_GROUP:
        CURRENT_EDIT_GROUP = new_group
        refresh_style_ui() 
        preview_selected() 
    else: refresh_style_ui()

def refresh_style_ui():
    global CURRENT_EDIT_GROUP, UI_REFRESHING
    UI_REFRESHING = True 
    if CURRENT_EDIT_GROUP not in GROUP_STYLES: UI_REFRESHING = False; return
    gs = GROUP_STYLES[CURRENT_EDIT_GROUP] 

    font_scale_var.set(gs["font_size"])
    max_lines_scale_var.set(gs.get("max_lines", 6))
    var_align.set(gs["text_align"])
    padding_l_scale_var.set(gs["padding_x_l"])
    padding_r_scale_var.set(gs["padding_x_r"])
    padding_t_scale_var.set(gs["padding_y_t"])
    padding_b_scale_var.set(gs["padding_y_b"])
    var_double_text.set(gs["double_enabled"])
    shadow_offset_scale_var.set(gs["shadow_offset"])
    var_outline.set(gs["outline_enabled"])
    outline_scale_var.set(gs["outline_width"])
    var_bg_enable.set(gs["bg_enabled"])
    var_textbox_model.set(gs["textbox_model"])
    bg_opacity_scale_var.set(gs["bg_opacity"])
    bg_min_opacity_scale_var.set(gs.get("bg_gradient_min", 0))
    var_bg_model.set(gs["bg_model"])
    var_bg_gradient_mode.set(gs["bg_gradient_mode"])
    bg_radius_scale_var.set(gs["bg_radius"])
    var_bg_border.set(gs["bg_border_enabled"])
    bg_border_scale_var.set(gs["bg_border_width"])
    wm_size_scale_var.set(gs["wm_size_percent"])
    wm_opacity_scale_var.set(gs["wm_opacity"])
    UI_REFRESHING = False

# =========================
# BULK PROCESSING
# =========================
def start_bulk_process():
    global global_zip_paths_for_bulk, zip_data, jpeg_quality
    
    accounts_to_process = []
    group_map = {} 
    for group_name, members in ACCOUNT_GROUPS.items():
        for member in members:
            if account_vars.get(member) and account_vars[member].get():
                accounts_to_process.append(member)
                group_map[member] = group_name

    if not global_zip_paths_for_bulk: return status_label.config(text="ERROR: Belum ada file ZIP.")
    if not accounts_to_process: return status_label.config(text="ERROR: Pilih akun.")
    if not os.path.isdir(OUTPUT_ROOT): os.makedirs(OUTPUT_ROOT, exist_ok=True)

    bulk_btn.config(state=tk.DISABLED); select_zip_btn.config(state=tk.DISABLED); output_btn.config(state=tk.DISABLED)
    status_label.config(text="Menghitung data..."); root.update_idletasks()
    selected_paths = get_selected_zip_paths()
    if not selected_paths:
        status_label.config(text='Tidak ada ZIP dicentang.')
        bulk_btn.config(state=tk.NORMAL); select_zip_btn.config(state=tk.NORMAL); return

    all_zips_data = {}
    total_processes = 0
    for path in selected_paths:
        try:
            zd = parse_zip(path)
            all_zips_data[path] = zd
            total_processes += len(zd) * len(accounts_to_process)
        except: pass

    progress_bar["maximum"] = total_processes; progress_bar["value"] = 0
    global_process_counter = 0; total_output_files = 0
    
    for path in selected_paths:
        zd = all_zips_data.get(path)
        if not zd: continue
        zip_out_dir = os.path.join(OUTPUT_ROOT, safe_filename(os.path.splitext(os.path.basename(path))[0]))
        os.makedirs(zip_out_dir, exist_ok=True)

        for kota, alamat in zd.keys():
            original_imgs = zd[(kota, alamat)]
            for account_name in accounts_to_process:
                try:
                    varied_base = build_account_specific_collage(original_imgs, account_name)
                    # KUNCI UTAMA: is_export=True untuk mengaktifkan penggantian teks otomatis
                    final = build_final_collage(original_imgs, kota, alamat, group_map[account_name], base_collage=varied_base, is_export=True)
                    
                    out_dir = os.path.join(zip_out_dir, safe_filename(account_name))
                    os.makedirs(out_dir, exist_ok=True)
                    final.save(os.path.join(out_dir, random_output_name(".jpg")), "JPEG", quality=jpeg_quality)
                    total_output_files += 1
                except: pass
                
                global_process_counter += 1
                progress_bar["value"] = global_process_counter
                if global_process_counter % 5 == 0:
                    status_label.config(text=f"Memproses {global_process_counter}/{total_processes}...")
                    root.update_idletasks()

    bulk_btn.config(state=tk.NORMAL); select_zip_btn.config(state=tk.NORMAL); output_btn.config(state=tk.NORMAL)
    status_label.config(text=f"SELESAI! {total_output_files} file dibuat.")

def show_output_folder():
    path = os.path.abspath(OUTPUT_ROOT)
    if os.path.exists(path):
        if sys.platform == "win32": os.startfile(path)
        elif sys.platform.startswith("linux"): subprocess.call(["xdg-open", path])
        elif sys.platform == "darwin": subprocess.call(["open", path])

# =========================
# PREVIEW & INTERACTION
# =========================
def get_selected_address_info():
    sel_indices = listbox_addresses.curselection()
    if not sel_indices: return None, None, None, None
    idx = sel_indices[0]
    if idx >= len(zip_keys): return None, None, None, None
    kota, alamat = zip_keys[idx]
    return kota, alamat, zip_data[(kota, alamat)], f"{kota}/{alamat}"

def get_canvas_and_items(canvas_name):
    if canvas_name == "liza": return preview_canvas_liza, GROUP_NAMES[0], canvas_items["liza"]
    elif canvas_name == "tiara": return preview_canvas_tiara, GROUP_NAMES[1], canvas_items["tiara"]
    return None, None, None

def update_preview_size(canvas_w, canvas_h):
    global preview_scale, preview_offset_x, preview_offset_y
    if canvas_w <= 0 or canvas_h <= 0: return 0, 0
    scale_w = canvas_w / CANVAS_W; scale_h = canvas_h / CANVAS_H
    preview_scale = min(scale_w, scale_h)
    new_w = int(CANVAS_W * preview_scale); new_h = int(CANVAS_H * preview_scale)
    preview_offset_x = (canvas_w - new_w) // 2; preview_offset_y = (canvas_h - new_h) // 2
    return new_w, new_h

def on_canvas_resize(event):
    if listbox_addresses.curselection(): preview_selected(target_canvas=event.widget.winfo_name())

def preview_selected(event=None, target_canvas=None):
    global preview_scale, preview_offset_x, preview_offset_y, base_collage_cache
    kota, alamat, images, cache_key = get_selected_address_info()
    if not images: return status_label.config(text="Pilih alamat.")
    if cache_key not in base_collage_cache: base_collage_cache[cache_key] = build_base_collage(images)
    base_collage = base_collage_cache[cache_key]
    canvases_to_update = []
    if target_canvas is None or target_canvas == "liza": canvases_to_update.append(("liza", preview_canvas_liza, canvas_items["liza"], GROUP_NAMES[0]))
    if target_canvas is None or target_canvas == "tiara": canvases_to_update.append(("tiara", preview_canvas_tiara, canvas_items["tiara"], GROUP_NAMES[1]))
    for canvas_name, canvas, items_dict, group_name in canvases_to_update:
        canvas.update_idletasks()
        new_w, new_h = update_preview_size(canvas.winfo_width(), canvas.winfo_height())
        # KUNCI UTAMA: is_export=False agar preview TETAP ALAMAT ASLI
        final_img = build_final_collage(images, kota, alamat, group_name, base_collage, is_export=False)
        final_img_small = final_img.resize((new_w, new_h), Image.LANCZOS)
        preview_cache[canvas_name]["base"] = ImageTk.PhotoImage(final_img_small)
        if items_dict["base"] is not None: canvas.delete(items_dict["base"])
        items_dict["base"] = canvas.create_image(preview_offset_x, preview_offset_y, anchor="nw", image=preview_cache[canvas_name]["base"])
        canvas.tag_lower(items_dict["base"])
        draw_interactive_overlays(canvas, items_dict, group_name, alamat)
    status_label.config(text=f"Preview: {kota}/{alamat}")

def textbox_start(event, canvas_name, cid):
    global drag_state
    drag_state.update({"id": cid, "canvas": canvas_name, "group": "Universal", "mode": "move_box", "x": event.x, "y": event.y, "pos_key": "textbox"})
    get_canvas_and_items(canvas_name)[0].tag_raise(cid)

def textbox_move(event):
    global drag_state, UNIVERSAL_POSITIONS, preview_scale, preview_offset_x, preview_offset_y
    if drag_state["mode"] != "move_box": return
    dx = event.x - drag_state["x"]; dy = event.y - drag_state["y"]
    x1, y1, x2, y2 = UNIVERSAL_POSITIONS["textbox"]
    new_x1 = x1 + dx; new_y1 = y1 + dy; new_x2 = x2 + dx; new_y2 = y2 + dy
    if new_x1 < preview_offset_x: dx -= (new_x1 - preview_offset_x); new_x1 = preview_offset_x; new_x2 = x2 + dx 
    if new_y1 < preview_offset_y: dy -= (new_y1 - preview_offset_y); new_y1 = preview_offset_y; new_y2 = y2 + dy 
    scaled_w = int(CANVAS_W * preview_scale); scaled_h = int(CANVAS_H * preview_scale)
    max_x = preview_offset_x + scaled_w; max_y = preview_offset_y + scaled_h
    if new_x2 > max_x: dx -= (new_x2 - max_x); new_x2 = max_x; new_x1 = x1 + dx 
    if new_y2 > max_y: dy -= (new_y2 - max_y); new_y2 = max_y; new_x1 = x1 + dx 
    new_coords = [new_x1, new_y1, new_x2, new_y2]
    preview_canvas_liza.coords(canvas_items["liza"]["textbox_rect"], *new_coords)
    preview_canvas_tiara.coords(canvas_items["tiara"]["textbox_rect"], *new_coords)
    drag_state["x"], drag_state["y"] = event.x, event.y
    UNIVERSAL_POSITIONS["textbox"] = new_coords

def textbox_resize_start(event, side):
    drag_state.update({"mode": f"resize_{side}", "x": event.x, "y": event.y})

def textbox_resize_move(event):
    global drag_state, UNIVERSAL_POSITIONS, preview_scale, preview_offset_x
    mode = drag_state.get("mode")
    if mode not in ("resize_left", "resize_right"): return
    dx = event.x - drag_state["x"]
    x1, y1, x2, y2 = UNIVERSAL_POSITIONS["textbox"]
    min_w = max(60, int(120 * preview_scale))
    if mode == "resize_left":
        new_x1 = x1 + dx
        if new_x1 < preview_offset_x: new_x1 = preview_offset_x
        if (x2 - new_x1) < min_w: new_x1 = x2 - min_w
        new_coords = [new_x1, y1, x2, y2]
    else:
        new_x2 = x2 + dx
        max_x = preview_offset_x + int(CANVAS_W * preview_scale)
        if new_x2 > max_x: new_x2 = max_x
        if (new_x2 - x1) < min_w: new_x2 = x1 + min_w
        new_coords = [x1, y1, new_x2, y2]
    for cname, c in (("liza", preview_canvas_liza), ("tiara", preview_canvas_tiara)):
        c.coords(canvas_items[cname]["textbox_rect"], *new_coords)
        hs = canvas_items[cname].get("textbox_handles") or []
        if len(hs) == 2:
            lh, rh = hs
            hx1, hx2, hy = new_coords[0], new_coords[2], (new_coords[1] + new_coords[3]) // 2
            c.coords(lh, hx1-6, hy-6, hx1+6, hy+6); c.coords(rh, hx2-6, hy-6, hx2+6, hy+6)
    UNIVERSAL_POSITIONS["textbox"] = new_coords; drag_state["x"], drag_state["y"] = event.x, event.y

def textbox_resize_release(event): drag_state["mode"] = None; preview_selected()
def textbox_release(event): drag_state["mode"] = None; preview_selected()

def wm_start(event, canvas_name, cid, group_name):
    global drag_state
    if cid != canvas_items[canvas_name]["watermark_rect"]: return
    drag_state.update({"id": cid, "canvas": canvas_name, "group": group_name, "mode": "move_wm", "x": event.x, "y": event.y, "pos_key": "watermark"})
    get_canvas_and_items(canvas_name)[0].tag_raise(cid)

def wm_move(event):
    global drag_state, preview_scale, preview_offset_x, preview_offset_y, GROUP_POSITIONS
    if drag_state["mode"] != "move_wm": return
    canvas_name = drag_state["canvas"]; group_name = drag_state["group"]
    canvas, _, _ = get_canvas_and_items(canvas_name)
    dx = event.x - drag_state["x"]; dy = event.y - drag_state["y"]
    canvas.move(drag_state["id"], dx, dy)
    cx_rel = max(0, min(CANVAS_W, (event.x - preview_offset_x) / preview_scale))
    cy_rel = max(0, min(CANVAS_H, (event.y - preview_offset_y) / preview_scale))
    GROUP_POSITIONS[group_name]["watermark"] = (cx_rel, cy_rel)
    drag_state["x"], drag_state["y"] = event.x, event.y
    items_dict = canvas_items[canvas_name]
    if items_dict["watermark_rect_text"]:
        canvas.coords(items_dict["watermark_rect_text"], event.x, items_dict["watermark_rect_text_y_offset"] + event.y)
    
def wm_release(event): drag_state["mode"] = None; preview_selected(target_canvas=drag_state["canvas"])

def draw_interactive_overlays(canvas, canvas_items_dict, group_name, alamat):
    global preview_scale, preview_offset_x, preview_offset_y, GROUP_POSITIONS, UNIVERSAL_POSITIONS, drag_state, grid_enabled
    s = preview_scale
    style = GROUP_STYLES[group_name]
    if canvas_items_dict["textbox_rect"]: canvas.delete(canvas_items_dict["textbox_rect"])
    if canvas_items_dict["watermark_rect"]: canvas.delete(canvas_items_dict["watermark_rect"])
    if canvas_items_dict["watermark_rect_text"]: canvas.delete(canvas_items_dict["watermark_rect_text"])
    for cid in canvas_items_dict["grid_lines"]: canvas.delete(cid)
    for cid in canvas_items_dict["textbox_handles"]: canvas.delete(cid)
    canvas_items_dict.update({"textbox_rect": None, "watermark_rect": None, "watermark_rect_text": None, "grid_lines": [], "textbox_handles": []})
    if grid_enabled: draw_grid_lines(canvas, canvas_items_dict, preview_offset_x, preview_offset_y, CANVAS_W * s, CANVAS_H * s)
    wm_img = watermark_imgs[group_name]
    if wm_img:
        wm_pos_rel = GROUP_POSITIONS[group_name]["watermark"]
        target_w_rel = max(1, int(CANVAS_W * (style["wm_size_percent"] / 100.0)))
        target_h_rel = int(wm_img.height * target_w_rel / wm_img.width)
        cx_p = int(preview_offset_x + wm_pos_rel[0] * s)
        cy_p = int(preview_offset_y + wm_pos_rel[1] * s)
        half_w_p, half_h_p = int(target_w_rel * s) // 2, int(target_h_rel * s) // 2
        cid_wm_rect = canvas.create_rectangle(cx_p - half_w_p, cy_p - half_h_p, cx_p + half_w_p, cy_p + half_h_p, outline='red', width=2, dash=(2, 2))
        canvas.tag_bind(cid_wm_rect, "<Button-1>", lambda e, c=canvas.winfo_name(), i=cid_wm_rect, g=group_name: wm_start(e, c, i, g))
        canvas.tag_bind(cid_wm_rect, "<B1-Motion>", wm_move); canvas.tag_bind(cid_wm_rect, "<ButtonRelease-1>", wm_release)
        canvas_items_dict["watermark_rect"] = cid_wm_rect
        cid_wm_text = canvas.create_text(cx_p, cy_p - half_h_p - 10, text=f"WM: {group_name}", fill="red", anchor="s")
        canvas_items_dict["watermark_rect_text"] = cid_wm_text
        canvas_items_dict["watermark_rect_text_y_offset"] = (cy_p - half_h_p - 10) - cy_p

    if not UNIVERSAL_POSITIONS["textbox"]:
        x1_rel, y1_rel = 100, CANVAS_H - 250
        x2_rel, y2_rel = CANVAS_W - 100, CANVAS_H - 50
        UNIVERSAL_POSITIONS["textbox"] = [int(preview_offset_x + x * s) for x in (x1_rel, y1_rel, x2_rel, y2_rel)]
    x1p, y1p, x2p, y2p = UNIVERSAL_POSITIONS["textbox"]
    cid_box_rect = canvas.create_rectangle(x1p, y1p, x2p, y2p, outline='cyan', width=2, dash=(4, 2))
    canvas.tag_bind(cid_box_rect, "<Button-1>", lambda e, c=canvas.winfo_name(), i=cid_box_rect: textbox_start(e, c, i))
    canvas.tag_bind(cid_box_rect, "<B1-Motion>", textbox_move); canvas.tag_bind(cid_box_rect, "<ButtonRelease-1>", textbox_release)
    canvas_items_dict["textbox_rect"] = cid_box_rect
    hy = (y1p + y2p) // 2
    cid_lh = canvas.create_rectangle(x1p-6, hy-6, x1p+6, hy+6, fill="cyan", outline="")
    cid_rh = canvas.create_rectangle(x2p-6, hy-6, x2p+6, hy+6, fill="cyan", outline="")
    canvas_items_dict["textbox_handles"] = [cid_lh, cid_rh]
    canvas.tag_bind(cid_lh, "<ButtonPress-1>", lambda e: textbox_resize_start(e, "left"))
    canvas.tag_bind(cid_lh, "<B1-Motion>", textbox_resize_move); canvas.tag_bind(cid_lh, "<ButtonRelease-1>", textbox_resize_release)
    canvas.tag_bind(cid_rh, "<ButtonPress-1>", lambda e: textbox_resize_start(e, "right"))
    canvas.tag_bind(cid_rh, "<B1-Motion>", textbox_resize_move); canvas.tag_bind(cid_rh, "<ButtonRelease-1>", textbox_resize_release)

def draw_grid_lines(canvas, items_dict, x_start, y_start, width, height):
    x_end, y_end = x_start + width, y_start + height
    lines_data = [
        (x_start + width/2, y_start, x_start + width/2, y_end, (4, 2)),
        (x_start, y_start + height/2, x_end, y_start + height/2, (4, 2)),
        (x_start + width/4, y_start, x_start + width/4, y_end, (2, 4)),
        (x_start + width*3/4, y_start, x_start + width*3/4, y_end, (2, 4)),
        (x_start, y_start + height/4, x_end, y_start + height/4, (2, 4)),
        (x_start, y_start + height*3/4, x_end, y_start + height*3/4, (2, 4)),
    ]
    for x1, y1, x2, y2, dash in lines_data:
        cid = canvas.create_line(x1, y1, x2, y2, fill='yellow', width=1, dash=dash)
        items_dict["grid_lines"].append(cid); canvas.tag_lower(cid)

# =========================
# UI SETUP
# =========================
root = tk.Tk()
MIRROR_ENABLED = tk.BooleanVar(value=False)
scale_debounce_id = None
root.title("Kolase Studio v7.3 PRO - Telegram Integrated")
root.geometry("1400x750")
style = ttk.Style()
try: style.theme_use('clam')
except: style.theme_use('default') 
DARK_BG, LIGHT_FG, LIGHT_BG = '#2e2e2e', 'white', "#f5f5f5"
WIDGET_BG, ACCENT_COLOR = '#3e3e3e', '#007bff'
root.configure(bg=DARK_BG)
style.configure('.', background=DARK_BG, foreground=LIGHT_FG)
style.configure('TFrame', background=DARK_BG)
style.configure('TLabelFrame', background=DARK_BG, foreground=LIGHT_FG, bordercolor=ACCENT_COLOR)
style.configure('TLabel', background=DARK_BG, foreground=LIGHT_FG)
style.configure('TCheckbutton', background=DARK_BG, foreground=LIGHT_FG, indicatorcolor=ACCENT_COLOR)
style.configure('TRadiobutton', background=DARK_BG, foreground=LIGHT_FG, indicatorcolor=ACCENT_COLOR)
style.configure('TButton', background=ACCENT_COLOR, foreground=LIGHT_FG, borderwidth=0)
style.map('TButton', background=[('active', '#0056b3')])
style.configure('TNotebook', background=DARK_BG, borderwidth=0)
style.map('TNotebook.Tab', background=[('selected', WIDGET_BG)], foreground=[('selected', LIGHT_FG)])
style.configure('TCombobox', fieldbackground=WIDGET_BG, foreground=LIGHT_FG, background=WIDGET_BG)
style.configure('TScale', background=DARK_BG, troughcolor=WIDGET_BG)
main_paned_window = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
main_paned_window.pack(fill="both", expand=True)
left_panel = ttk.Frame(main_paned_window, width=350)
main_paned_window.add(left_panel, weight=0)
right_panel = ttk.Frame(main_paned_window)
main_paned_window.add(right_panel, weight=1)
left_canvas = tk.Canvas(left_panel, bg=DARK_BG, highlightthickness=0)
left_canvas.pack(side="left", fill="both", expand=True)
left_scrollbar = ttk.Scrollbar(left_panel, orient="vertical", command=left_canvas.yview)
left_scrollbar.pack(side="right", fill="y")
left_canvas.configure(yscrollcommand=left_scrollbar.set)
left_content_frame = ttk.Frame(left_canvas)
left_content_frame.bind('<Configure>', lambda e: left_canvas.configure(scrollregion=left_canvas.bbox("all")))
left_canvas.bind_all("<MouseWheel>", lambda e: left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
left_canvas.create_window((0, 0), window=left_content_frame, anchor="nw", width=340)
status_label = tk.Label(root, text="Kolase Studio v7.3 Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W, bg='#1e1e1e', fg='white')
status_label.pack(side=tk.BOTTOM, fill=tk.X)
account_list_frame = ttk.LabelFrame(left_content_frame, text="Pilih Akun yang Diproses", padding=5)
account_list_frame.pack(fill="x", pady=5, padx=5)
def toggle_group_check(group_name):
    group_var = account_vars[group_name].get()
    for member in ACCOUNT_GROUPS[group_name]: account_vars[member].set(group_var)
def toggle_member_check(group_name):
    all_checked = all(account_vars[member].get() for member in ACCOUNT_GROUPS[group_name])
    if all_checked != account_vars[group_name].get(): account_vars[group_name].set(all_checked)
for group_name, members in ACCOUNT_GROUPS.items():
    account_vars[group_name] = tk.BooleanVar(value=False)
    ttk.Checkbutton(account_list_frame, text=f"AKTIFKAN SEMUA ({group_name})", variable=account_vars[group_name], command=lambda g=group_name: toggle_group_check(g)).pack(anchor="w", padx=5, pady=(5, 0))
    member_frame = ttk.Frame(account_list_frame)
    member_frame.pack(fill="x", padx=15, pady=2)
    half = math.ceil(len(members) / 2)
    col1, col2 = members[:half], members[half:]
    col1_frame = ttk.Frame(member_frame); col1_frame.pack(side="left", fill="y")
    for member in col1:
        account_vars[member] = tk.BooleanVar(value=False)
        ttk.Checkbutton(col1_frame, text=member, variable=account_vars[member], command=lambda g=group_name: toggle_member_check(g)).pack(anchor="w")
    col2_frame = ttk.Frame(member_frame); col2_frame.pack(side="left", fill="y", padx=20)
    for member in col2:
        account_vars[member] = tk.BooleanVar(value=False)
        ttk.Checkbutton(col2_frame, text=member, variable=account_vars[member], command=lambda g=group_name: toggle_member_check(g)).pack(anchor="w")
custom_accounts_frame = ttk.LabelFrame(left_content_frame, text="Tambah Akun Baru", padding=5)
custom_accounts_frame.pack(fill="x", pady=5, padx=5)
var_custom_name = tk.StringVar(value="")
ttk.Entry(custom_accounts_frame, textvariable=var_custom_name).pack(fill="x", pady=(0, 6))
var_custom_group = tk.StringVar(value=GROUP_NAMES[0] if GROUP_NAMES else "")
combo_custom_group = ttk.Combobox(custom_accounts_frame, textvariable=var_custom_group, values=GROUP_NAMES, state="readonly")
combo_custom_group.pack(fill="x", pady=(0, 6))
custom_btn_row = ttk.Frame(custom_accounts_frame); custom_btn_row.pack(fill="x", pady=(0, 6))
custom_checks_frame = ttk.Frame(custom_accounts_frame); custom_checks_frame.pack(fill="x", pady=(0, 6))
custom_listbox = tk.Listbox(custom_accounts_frame, height=6, exportselection=0, bg=WIDGET_BG, fg=LIGHT_FG, selectbackground=ACCENT_COLOR, highlightthickness=0)
custom_listbox.pack(fill="x", pady=(0, 6))
_custom_check_widgets = []
_DEFAULTS_LOWER = set()
for g, arr in DEFAULT_ACCOUNT_GROUPS.items():
    for nm in arr: _DEFAULTS_LOWER.add(str(nm).strip().lower())
def refresh_custom_accounts_ui():
    global _custom_check_widgets
    for w in _custom_check_widgets: w.destroy()
    _custom_check_widgets = []
    custom_listbox.delete(0, tk.END)
    custom_map = {}
    for g, arr in ACCOUNT_GROUPS.items():
        cust = [str(nm).strip() for nm in arr if str(nm).strip() and str(nm).strip().lower() not in _DEFAULTS_LOWER]
        if cust: custom_map[g] = cust
    for g, arr in custom_map.items():
        lbl = ttk.Label(custom_checks_frame, text=f"[{g}]")
        lbl.pack(anchor="w"); _custom_check_widgets.append(lbl)
        for nm in arr:
            if nm not in account_vars: account_vars[nm] = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(custom_checks_frame, text=nm, variable=account_vars[nm], command=lambda gg=g: toggle_member_check(gg))
            cb.pack(anchor="w", padx=10); _custom_check_widgets.append(cb)
            custom_listbox.insert(tk.END, f"{nm} — {g}")
    combo_custom_group.configure(values=GROUP_NAMES)
def add_custom_account():
    name = _normalize_account_name(var_custom_name.get()); group = var_custom_group.get().strip()
    if not name or not group or group not in ACCOUNT_GROUPS: return
    if _is_duplicate_account(name, ACCOUNT_GROUPS): return
    ACCOUNT_GROUPS[group].append(name); account_vars[name] = tk.BooleanVar(value=True)
    _save_custom_accounts({g: [x for x in ACCOUNT_GROUPS[g] if str(x).strip().lower() not in _DEFAULTS_LOWER] for g in ACCOUNT_GROUPS})
    var_custom_name.set(""); refresh_custom_accounts_ui()
def remove_selected_custom_account():
    sel = custom_listbox.curselection()
    if not sel: return
    text = custom_listbox.get(sel[0])
    if " — " not in text: return
    name, group = text.split(" — ", 1); name, group = name.strip(), group.strip()
    if group in ACCOUNT_GROUPS: ACCOUNT_GROUPS[group] = [x for x in ACCOUNT_GROUPS[group] if str(x).strip() != name]
    if name in account_vars and name.lower() not in _DEFAULTS_LOWER: del account_vars[name]
    _save_custom_accounts({g: [x for x in ACCOUNT_GROUPS[g] if str(x).strip().lower() not in _DEFAULTS_LOWER] for g in ACCOUNT_GROUPS})
    refresh_custom_accounts_ui()
ttk.Button(custom_btn_row, text="Tambah Akun", command=add_custom_account).pack(side="left", fill="x", expand=True)
ttk.Button(custom_btn_row, text="Hapus yang Dipilih", command=remove_selected_custom_account).pack(side="left", fill="x", expand=True, padx=(6, 0))
refresh_custom_accounts_ui()
select_zip_btn = ttk.Button(left_content_frame, text="1. Pilih FOLDER ZIP", command=choose_zip)
select_zip_btn.pack(fill="x", pady=5, padx=5)
zip_check_frame = ttk.LabelFrame(left_content_frame, text="ZIP yang Diproses", padding=5)
zip_check_frame.pack(fill="both", expand=False, pady=5, padx=5)
zip_check_canvas = tk.Canvas(zip_check_frame, height=180, bg=LIGHT_BG, highlightthickness=0)
zip_check_scroll = ttk.Scrollbar(zip_check_frame, orient="vertical", command=zip_check_canvas.yview)
zip_check_inner = ttk.Frame(zip_check_canvas)
zip_check_inner.bind("<Configure>", lambda e: zip_check_canvas.configure(scrollregion=zip_check_canvas.bbox("all")))
_zip_window_id = zip_check_canvas.create_window((0, 0), window=zip_check_inner, anchor="nw")
zip_check_canvas.bind("<Configure>", lambda e: zip_check_canvas.itemconfigure(_zip_window_id, width=zip_check_canvas.winfo_width()))
zip_check_canvas.configure(yscrollcommand=zip_check_scroll.set)
zip_check_canvas.pack(side="left", fill="both", expand=True)
zip_check_scroll.pack(side="right", fill="y")
zip_check_ui.update({"frame": zip_check_frame, "canvas": zip_check_canvas, "inner": zip_check_inner, "scroll": zip_check_scroll})
address_frame = ttk.LabelFrame(left_content_frame, text="2. Daftar Alamat (Preview)", padding=5)
address_frame.pack(fill="x", pady=5, padx=5)
listbox_addresses = tk.Listbox(address_frame, height=8, exportselection=0, bg=WIDGET_BG, fg=LIGHT_FG, selectbackground=ACCENT_COLOR, highlightthickness=0)
listbox_addresses.pack(side="left", fill="both", expand=True)
listbox_addresses.bind('<<ListboxSelect>>', preview_selected)
ttk.Scrollbar(address_frame, orient="vertical", command=listbox_addresses.yview).pack(side="right", fill="y")
listbox_addresses.config(yscrollcommand=listbox_addresses.yview)
edit_group_frame = ttk.Frame(left_content_frame)
edit_group_frame.pack(fill="x", padx=5, pady=(5, 0))
ttk.Label(edit_group_frame, text="Grup Edit:").pack(side="left", padx=(0, 5))
var_edit_group = tk.StringVar(value=CURRENT_EDIT_GROUP)
group_combo = ttk.Combobox(edit_group_frame, textvariable=var_edit_group, values=GROUP_NAMES, state="readonly", width=20)
group_combo.pack(side="left", fill="x", expand=True)
group_combo.bind("<<ComboboxSelected>>", change_edit_group)
ttk.Checkbutton(left_content_frame, text="Mirror setting box ke grup lain", variable=MIRROR_ENABLED, command=lambda: (apply_mirror_from(CURRENT_EDIT_GROUP), refresh_style_ui(), preview_selected())).pack(anchor="w", padx=5)
bulk_btn = ttk.Button(left_content_frame, text="3. JALANKAN PROSES BULK", command=start_bulk_process)
bulk_btn.pack(fill="x", pady=10, padx=5)
progress_bar = ttk.Progressbar(left_content_frame, orient="horizontal", mode="determinate")
progress_bar.pack(fill="x", pady=5, padx=5)
output_btn = ttk.Button(left_content_frame, text="Buka Folder Output", command=show_output_folder, state=tk.DISABLED)
output_btn.pack(fill="x", pady=5, padx=5)
jpeg_quality_frame = ttk.LabelFrame(left_content_frame, text="Pengaturan Global", padding=5)
jpeg_quality_frame.pack(fill="x", pady=5, padx=5)
jpeg_quality_label = ttk.Label(jpeg_quality_frame, text=f"Kualitas JPEG: {jpeg_quality}%")
jpeg_quality_label.pack(anchor="w")
ttk.Scale(jpeg_quality_frame, from_=50, to=100, orient="horizontal", command=on_quality_change, variable=tk.DoubleVar(value=jpeg_quality)).pack(fill="x")
style_notebook = ttk.Notebook(left_content_frame)
style_notebook.pack(fill="x", expand=False, padx=5, pady=5)
tab_text = ttk.Frame(style_notebook, padding="5"); style_notebook.add(tab_text, text="Teks")
ttk.Label(tab_text, text="Ukuran Font").pack(anchor="w")
font_scale_var = tk.DoubleVar(value=DEFAULT_STYLE["font_size"])
ttk.Scale(tab_text, from_=10, to=150, orient="horizontal", variable=font_scale_var, command=lambda val: on_scale_change("font_size", val)).pack(fill="x", pady=(0, 10))
ttk.Label(tab_text, text="Max Baris").pack(anchor="w")
max_lines_scale_var = tk.DoubleVar(value=6)
ttk.Scale(tab_text, from_=3, to=12, orient="horizontal", variable=max_lines_scale_var, command=lambda val: on_scale_change("max_lines", val)).pack(fill="x")
ttk.Button(tab_text, text="Font Alamat", command=choose_font).pack(fill="x", pady=5)
ttk.Button(tab_text, text="Warna Teks", command=lambda: choose_style_color("text_color", DEFAULT_STYLE["text_color"])).pack(fill="x", pady=5)
var_align = tk.StringVar(value=DEFAULT_STYLE["text_align"])
align_frame = ttk.Frame(tab_text); align_frame.pack(fill="x")
for mode in ["left", "center", "right"]: ttk.Radiobutton(align_frame, text=mode.title(), variable=var_align, value=mode, command=lambda: on_radio_change("text_align", var_align)).pack(side="left", padx=5)
var_double_text = tk.IntVar(value=0)
ttk.Checkbutton(tab_text, text="Shadow Text", variable=var_double_text, command=lambda: on_toggle_change("double_enabled", var_double_text)).pack(anchor="w")
ttk.Button(tab_text, text="Warna Shadow", command=lambda: choose_style_color("shadow_color", DEFAULT_STYLE["shadow_color"])).pack(fill="x")
shadow_offset_scale_var = tk.DoubleVar(value=3)
ttk.Scale(tab_text, from_=0, to=15, orient="horizontal", variable=shadow_offset_scale_var, command=lambda val: on_scale_change("shadow_offset", val)).pack(fill="x")
var_outline = tk.IntVar(value=0)
ttk.Checkbutton(tab_text, text="Outline", variable=var_outline, command=lambda: on_toggle_change("outline_enabled", var_outline)).pack(anchor="w")
ttk.Button(tab_text, text="Warna Outline", command=lambda: choose_style_color("outline_color", DEFAULT_STYLE["outline_color"])).pack(fill="x")
outline_scale_var = tk.DoubleVar(value=2)
ttk.Scale(tab_text, from_=0, to=10, orient="horizontal", variable=outline_scale_var, command=lambda val: on_scale_change("outline_width", val)).pack(fill="x")
ttk.Label(tab_text, text="Padding X (L/R)").pack(anchor="w")
padding_l_scale_var = tk.DoubleVar(value=30); ttk.Scale(tab_text, from_=0, to=100, orient="horizontal", variable=padding_l_scale_var, command=lambda val: on_scale_change("padding_x_l", val)).pack(fill="x")
padding_r_scale_var = tk.DoubleVar(value=30); ttk.Scale(tab_text, from_=0, to=100, orient="horizontal", variable=padding_r_scale_var, command=lambda val: on_scale_change("padding_x_r", val)).pack(fill="x")
ttk.Label(tab_text, text="Padding Y (T/B)").pack(anchor="w")
padding_t_scale_var = tk.DoubleVar(value=30); ttk.Scale(tab_text, from_=0, to=100, orient="horizontal", variable=padding_t_scale_var, command=lambda val: on_scale_change("padding_y_t", val)).pack(fill="x")
padding_b_scale_var = tk.DoubleVar(value=30); ttk.Scale(tab_text, from_=0, to=100, orient="horizontal", variable=padding_b_scale_var, command=lambda val: on_scale_change("padding_y_b", val)).pack(fill="x")
tab_bg = ttk.Frame(style_notebook, padding="5"); style_notebook.add(tab_bg, text="Area Teks")
var_bg_enable = tk.IntVar(value=1); ttk.Checkbutton(tab_bg, text="Aktifkan BG", variable=var_bg_enable, command=lambda: on_toggle_change("bg_enabled", var_bg_enable)).pack(anchor="w")
var_textbox_model = tk.StringVar(value="bottom")
model_pos_frame = ttk.Frame(tab_bg); model_pos_frame.pack(fill="x")
for mode in ["bottom", "center", "corner"]: ttk.Radiobutton(model_pos_frame, text=mode.title(), variable=var_textbox_model, value=mode, command=lambda: on_radio_change("textbox_model", var_textbox_model)).pack(side="left", padx=5)
ttk.Button(tab_bg, text="Warna BG", command=lambda: choose_style_color("bg_color", DEFAULT_STYLE["bg_color"])).pack(fill="x", pady=5)
ttk.Label(tab_bg, text="Opasitas Utama (Solid / Start)").pack(anchor="w")
bg_opacity_scale_var = tk.DoubleVar(value=200)
ttk.Scale(tab_bg, from_=0, to=255, orient="horizontal", variable=bg_opacity_scale_var, command=lambda val: on_scale_change("bg_opacity", val)).pack(fill="x")
ttk.Label(tab_bg, text="Opasitas Pudar (Gradient End)").pack(anchor="w")
bg_min_opacity_scale_var = tk.DoubleVar(value=0)
ttk.Scale(tab_bg, from_=0, to=255, orient="horizontal", variable=bg_min_opacity_scale_var, command=lambda val: on_scale_change("bg_gradient_min", val)).pack(fill="x")
var_bg_gradient_mode = tk.StringVar(value="solid")
grad_frame = ttk.Frame(tab_bg); grad_frame.pack(fill="x", pady=5)
for m, l in [("solid", "Solid"), ("left_to_right_blur", "L>R"), ("right_to_left_blur", "R>L"), ("center_blur", "Ctr")]:
    ttk.Radiobutton(grad_frame, text=l, variable=var_bg_gradient_mode, value=m, command=lambda: on_radio_change("bg_gradient_mode", var_bg_gradient_mode)).pack(side="left")
var_bg_model = tk.StringVar(value="rounded")
shape_combo = ttk.Combobox(tab_bg, values=ALL_SHAPES_LIST, textvariable=var_bg_model, state="readonly", height=15)
shape_combo.pack(fill="x", pady=5)
shape_combo.bind("<<ComboboxSelected>>", lambda e: on_radio_change("bg_model", var_bg_model))
var_bg_corner_mode = tk.StringVar(value="both")
corner_frame = ttk.Frame(tab_bg); corner_frame.pack(fill="x")
for m, l in [("left", "Kiri"), ("right", "Kanan"), ("both", "2nya")]:
    ttk.Radiobutton(corner_frame, text=l, variable=var_bg_corner_mode, value=m, command=lambda: on_radio_change("bg_corner_mode", var_bg_corner_mode)).pack(side="left")
bg_radius_scale_var = tk.DoubleVar(value=40); ttk.Scale(tab_bg, from_=0, to=200, orient="horizontal", variable=bg_radius_scale_var, command=lambda val: on_scale_change("bg_radius", val)).pack(fill="x")
var_bg_border = tk.IntVar(value=1); ttk.Checkbutton(tab_bg, text="Border", variable=var_bg_border, command=lambda: on_toggle_change("bg_border_enabled", var_bg_border)).pack(anchor="w")
ttk.Button(tab_bg, text="Warna Border", command=lambda: choose_style_color("bg_border_color", DEFAULT_STYLE["bg_border_color"])).pack(fill="x")
bg_border_scale_var = tk.DoubleVar(value=4); ttk.Scale(tab_bg, from_=0, to=10, orient="horizontal", variable=bg_border_scale_var, command=lambda val: on_scale_change("bg_border_width", val)).pack(fill="x")
tab_wm = ttk.Frame(style_notebook, padding="5"); style_notebook.add(tab_wm, text="Watermark")
ttk.Button(tab_wm, text=f"Pilih WM ({GROUP_NAMES[0]})", command=lambda: choose_watermark(GROUP_NAMES[0])).pack(fill="x", pady=5)
ttk.Button(tab_wm, text=f"Pilih WM ({GROUP_NAMES[1]})", command=lambda: choose_watermark(GROUP_NAMES[1])).pack(fill="x", pady=5)
ttk.Label(tab_wm, text="Ukuran WM (%)").pack(anchor="w")
wm_size_scale_var = tk.DoubleVar(value=25); ttk.Scale(tab_wm, from_=0, to=100, orient="horizontal", variable=wm_size_scale_var, command=lambda val: on_scale_change("wm_size_percent", val)).pack(fill="x")
ttk.Label(tab_wm, text="Opasitas WM").pack(anchor="w")
wm_opacity_scale_var = tk.DoubleVar(value=255); ttk.Scale(tab_wm, from_=0, to=255, orient="horizontal", variable=wm_opacity_scale_var, command=lambda val: on_scale_change("wm_opacity", val)).pack(fill="x")
tab_export = ttk.Frame(style_notebook, padding="5"); style_notebook.add(tab_export, text="Ekspor")
var_grid = tk.IntVar(value=0); ttk.Checkbutton(tab_export, text="Tampilkan Grid (Preview)", variable=var_grid, command=on_grid_toggle_change).pack(anchor="w")
preview_frame = ttk.Frame(right_panel)
preview_frame.pack(fill="both", expand=True, padx=5, pady=5)
liza_frame = ttk.LabelFrame(preview_frame, text=GROUP_NAMES[0], padding=5)
liza_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
preview_canvas_liza = tk.Canvas(liza_frame, bg=DARK_BG, highlightthickness=0)
preview_canvas_liza.pack(fill="both", expand=True)
preview_canvas_liza.winfo_name = lambda: "liza"
preview_canvas_liza.bind('<Configure>', on_canvas_resize)
tiara_frame = ttk.LabelFrame(preview_frame, text=GROUP_NAMES[1], padding=5)
tiara_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))
preview_canvas_tiara = tk.Canvas(tiara_frame, bg=DARK_BG, highlightthickness=0)
preview_canvas_tiara.pack(fill="both", expand=True)
preview_canvas_tiara.winfo_name = lambda: "tiara"
preview_canvas_tiara.bind('<Configure>', on_canvas_resize)
refresh_style_ui()
if __name__ == "__main__":
    root.mainloop()