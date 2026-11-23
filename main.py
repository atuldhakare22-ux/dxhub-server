import os
import json
import time
import random
import string
import asyncio
from pyrogram import Client, filters
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))

DB_FILE = "dxhub_db.json"
os.makedirs("thumbs", exist_ok=True)

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"videos": {}, "publishers": {}, "vip_keys": {}}

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

db = load_db()

bot = Client("dxhub_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def gen_code(length=7):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await message.reply_text(
        "👋 **DX HUB Cloud Bot में स्वागत है!**\n\n"
        "📤 **वीडियो अपलोड:** मुझे कोई भी वीडियो भेजें या फॉरवर्ड करें — मैं थंबनेल निकालकर **Watch Link** और **More Videos Link** दे दूँगा।\n\n"
        "🔑 **VIP Key (₹299/mo):** `/genkey 30` भेजें।"
    )

@bot.on_message(filters.command("genkey") & filters.private)
async def gen_vip_key(client, message):
    try:
        days = int(message.text.split()[1]) if len(message.text.split()) > 1 else 30
    except:
        days = 30
    key = f"DXVIP-{random.randint(1000,9999)}-{gen_code(4).upper()}"
    expiry = int(time.time()) + (days * 86400)
    db["vip_keys"][key] = {"expiry": expiry, "days": days}
    save_db(db)
    await message.reply_text(
        f"✅ **नई DX HUB VIP Key तैयार है!**\n\n"
        f"🔑 **Key:** `{key}`\n"
        f"⏳ **वैधता:** {days} दिन (100% Ad-Free)\n\n"
        f"इसे यूज़र को भेज दें।"
    )

@bot.on_message(filters.video & filters.private)
async def handle_video(client, message):
    status = await message.reply_text("⏳ **वीडियो प्रोसेस हो रहा है...**")
    pub_id = str(message.from_user.id)
    vid_code = f"{random.randint(10000,99999)}_{random.randint(1,9)}"
    
    sent = await message.copy(CHANNEL_ID, caption=f"ID: {vid_code} | Pub: {pub_id}")
    
    thumb_path = f"thumbs/{vid_code}.jpg"
    if message.video.thumbs:
        await client.download_media(message.video.thumbs[0].file_id, file_name=thumb_path)
    
    size_mb = round((message.video.file_size or 0) / (1024 * 1024), 1)
    duration = message.video.duration or 0
    
    video_entry = {
        "vid_id": vid_code,
        "msg_id": sent.id,
        "pub_id": pub_id,
        "safe_name": f"{vid_code}_.mp4",
        "size_mb": size_mb,
        "duration": duration,
        "has_thumb": os.path.exists(thumb_path),
        "created_at": int(time.time())
    }
    db["videos"][vid_code] = video_entry
    if pub_id not in db["publishers"]:
        db["publishers"][pub_id] = []
    db["publishers"][pub_id].insert(0, vid_code)
    save_db(db)
    
    server_url = os.environ.get("RENDER_EXTERNAL_URL", "https://dxhub-server.onrender.com")
    watch_url = f"{server_url}/watch/{vid_code}?unlock=DX1234"
    channel_url = f"{server_url}/channel/{pub_id}?unlock=DX1234"
    
    caption_text = (
        f"🎬 **नई वीडियो फाइल तैयार है!**\n"
        f"📁 **File:** `{vid_code}_.mp4` ({size_mb} MB)\n\n"
        f"▶️ **Watch & Download Link:**\n{watch_url}\n\n"
        f"📂 **More Videos (चैनल की सभी वीडियो):**\n{channel_url}"
    )
    
    await status.delete()
    if os.path.exists(thumb_path):
        await message.reply_photo(photo=thumb_path, caption=caption_text)
    else:
        await message.reply_text(caption_text)

@app.get("/")
async def home():
    return {"status": "DX HUB Server Running", "total_videos": len(db["videos"])}

@app.get("/api/video/{vid_id}")
async def get_video_info(vid_id: str):
    if vid_id not in db["videos"]:
        raise HTTPException(status_code=404, detail="Video not found")
    vid = db["videos"][vid_id]
    pub_id = vid["pub_id"]
    more_ids = db["publishers"].get(pub_id, [])[:20]
    more_videos = [db["videos"][i] for i in more_ids if i in db["videos"] and i != vid_id]
    return {"video": vid, "more_videos": more_videos}

@app.get("/api/channel/{pub_id}")
async def get_channel_videos(pub_id: str):
    vids = [db["videos"][i] for i in db["publishers"].get(pub_id, []) if i in db["videos"]]
    return {"pub_id": pub_id, "videos": vids}

@app.get("/api/thumb/{vid_id}")
async def get_thumb(vid_id: str):
    path = f"thumbs/{vid_id}.jpg"
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="No thumbnail")

@app.get("/api/verify_vip/{key}")
async def verify_vip(key: str):
    key = key.strip().upper()
    if key in db["vip_keys"] and db["vip_keys"][key]["expiry"] > int(time.time()):
        return {"valid": True, "expiry": db["vip_keys"][key]["expiry"]}
    return {"valid": False}

@app.get("/stream/{vid_id}")
async def stream_video(vid_id: str, request: Request):
    if vid_id not in db["videos"]:
        raise HTTPException(status_code=404, detail="Video not found")
    msg_id = db["videos"][vid_id]["msg_id"]
    msg = await bot.get_messages(CHANNEL_ID, msg_id)
    file_size = msg.video.file_size
    
    range_header = request.headers.get("range")
    start = 0
    end = file_size - 1
    if range_header:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        
    async def file_generator():
        async for chunk in bot.stream_media(msg, offset=start // (1024 * 1024)):
            yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Type": "video/mp4",
    }
    return StreamingResponse(file_generator(), status_code=206 if range_header else 200, headers=headers)

@app.get("/watch/{vid_id}")
async def deep_link_redirect(vid_id: str, unlock: str = ""):
    html = f"""
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>DX HUB - Opening File</title></head>
    <body style="background:#0a0f12;color:white;font-family:sans-serif;text-align:center;padding-top:80px;">
    <h2>Opening DX HUB App...</h2>
    <p>File ID: {vid_id}_.mp4</p>
    <a href="dxhub://watch/{vid_id}?unlock={unlock}" style="background:#10b981;color:white;padding:14px 28px;border-radius:10px;text-decoration:none;font-weight:bold;display:inline-block;margin-top:20px;">Open in DX HUB App</a>
    <script>window.location.href = "dxhub://watch/{vid_id}?unlock={unlock}";</script>
    </body></html>
    """
    return HTMLResponse(content=html)

async def start_services():
    await bot.start()
    port = int(os.environ.get("PORT", 10000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(start_services())
