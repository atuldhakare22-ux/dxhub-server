import os
import json
import time
import random
import string
import asyncio
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TG_FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

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
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def gen_code(length=7):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

async def send_msg(client, chat_id, text):
    await client.post(f"{TG_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })

async def telegram_poller():
    offset = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.get(f"{TG_API}/deleteWebhook")
        while True:
            try:
                res = await client.get(f"{TG_API}/getUpdates", params={"offset": offset, "timeout": 20})
                data = res.json()
                if not data.get("ok"):
                    await asyncio.sleep(3)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message")
                    if not msg:
                        continue

                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")

                    if text.startswith("/start"):
                        await send_msg(client, chat_id,
                            "👋 **DX HUB Official Bot चालू हो गया है!**\n\n"
                            "📤 **वीडियो अपलोड:** मुझे कोई भी वीडियो भेजें या फॉरवर्ड करें — मैं तुरंत **Watch Link** और **More Videos Link** दे दूँगा।\n\n"
                            "🔑 **VIP Key (₹299/mo):** `/genkey 30` भेजें।"
                        )

                    elif text.startswith("/genkey"):
                        parts = text.split()
                        days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 30
                        key = f"DXVIP-{random.randint(1000,9999)}-{gen_code(4).upper()}"
                        expiry = int(time.time()) + (days * 86400)
                        db["vip_keys"][key] = {"expiry": expiry, "days": days}
                        save_db(db)
                        await send_msg(client, chat_id,
                            f"✅ **नई DX HUB VIP Key तैयार है!**\n\n"
                            f"🔑 **Key:** `{key}`\n"
                            f"⏳ **वैधता:** {days} दिन (100% Ad-Free)"
                        )

                    elif "video" in msg:
                        video = msg["video"]
                        file_id = video["file_id"]
                        pub_id = str(chat_id)
                        vid_code = f"{random.randint(10000,99999)}_{random.randint(1,9)}"
                        size_mb = round((video.get("file_size", 0)) / (1024 * 1024), 1)
                        duration = video.get("duration", 0)

                        if CHANNEL_ID:
                            await client.post(f"{TG_API}/copyMessage", json={
                                "chat_id": CHANNEL_ID,
                                "from_chat_id": chat_id,
                                "message_id": msg["message_id"],
                                "caption": f"ID: {vid_code}"
                            })

                        thumb_path = f"thumbs/{vid_code}.jpg"
                        thumb_obj = video.get("thumbnail") or video.get("thumb")
                        if thumb_obj:
                            f_info = (await client.get(f"{TG_API}/getFile", params={"file_id": thumb_obj["file_id"]})).json()
                            if f_info.get("ok"):
                                f_path = f_info["result"]["file_path"]
                                img_data = await client.get(f"{TG_FILE_API}/{f_path}")
                                with open(thumb_path, "wb") as tf:
                                    tf.write(img_data.content)

                        db["videos"][vid_code] = {
                            "vid_id": vid_code,
                            "file_id": file_id,
                            "pub_id": pub_id,
                            "safe_name": f"{vid_code}_.mp4",
                            "size_mb": size_mb,
                            "duration": duration,
                            "has_thumb": os.path.exists(thumb_path),
                            "created_at": int(time.time())
                        }
                        if pub_id not in db["publishers"]:
                            db["publishers"][pub_id] = []
                        db["publishers"][pub_id].insert(0, vid_code)
                        save_db(db)

                        server_url = os.environ.get("RENDER_EXTERNAL_URL", "https://dxhub-server.onrender.com").rstrip("/")
                        watch_url = f"{server_url}/watch/{vid_code}?unlock=DX1234"
                        channel_url = f"{server_url}/channel/{pub_id}?unlock=DX1234"

                        await send_msg(client, chat_id,
                            f"🎬 **नई वीडियो फाइल तैयार है!**\n"
                            f"📁 **File:** `{vid_code}_.mp4` ({size_mb} MB)\n\n"
                            f"▶️ **Watch & Download Link:**\n{watch_url}\n\n"
                            f"📂 **More Videos Link:**\n{channel_url}"
                        )
            except Exception as e:
                print("Polling error:", e)
                await asyncio.sleep(3)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(telegram_poller())

@app.get("/")
async def home():
    return {"status": "DX HUB Bot & Server Live", "total_videos": len(db["videos"])}

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
    file_id = db["videos"][vid_id]["file_id"]
    async with httpx.AsyncClient() as client:
        f_info = (await client.get(f"{TG_API}/getFile", params={"file_id": file_id})).json()
        if not f_info.get("ok"):
            raise HTTPException(status_code=400, detail="File too large or invalid")
        file_url = f"{TG_FILE_API}/{f_info['result']['file_path']}"

    range_header = request.headers.get("range")
    req_headers = {"Range": range_header} if range_header else {}

    async def stream_gen():
        async with httpx.AsyncClient(timeout=None) as s_client:
            async with s_client.stream("GET", file_url, headers=req_headers) as r:
                async for chunk in r.aiter_bytes(chunk_size=512 * 1024):
                    yield chunk

    return StreamingResponse(stream_gen(), media_type="video/mp4")

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
