"""
Runner script - resolves short TikTok URL and sends 1000 shares.
Also serves an HTML dashboard on http://localhost:8080
Usage: python run_shares.py
"""

import asyncio
import json
import math
import os
import random
import ssl
import sys
import threading
import time
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from data.lists import PLATFORMS, DEVICE_TYPES, APP_DOMAINS, CHANNELS
from data.user_agents import USER_AGENTS

import logging

# Set up logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("bot")

# -- SSL workaround --
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# -- Configuration --
VIDEO_URL    = "https://vt.tiktok.com/zs9rcfhds/"
SHARE_AMOUNT = 1000

# -- Shared state --
class ShareVariables:
    sent_requests       = 0
    successful_requests = 0
    failed_requests     = 0
    completed           = False
    video_id            = ""
    status_msg          = "Waiting to start..."
    started             = False

    def reset(self):
        self.sent_requests       = 0
        self.successful_requests = 0
        self.failed_requests     = 0
        self.completed           = False
        self.video_id            = ""
        self.status_msg          = "Initializing..."
        self.started             = False


share_vars = ShareVariables()


# -- Helper: resolve short URL to video ID --
async def resolve_video_id(url):
    connector = aiohttp.TCPConnector(ssl=False)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        parsed = urlparse(url)
        host   = (parsed.hostname or "").lower()
        if host in ("vm.tiktok.com", "vt.tiktok.com"):
            async with session.get(url, allow_redirects=True) as resp:
                final_url = str(resp.url)
                print("  Redirected to: " + final_url)
            parsed = urlparse(final_url)
        parts = parsed.path.split("/")
        # Try to find a numeric video ID in the path
        for part in reversed(parts):
            if part.isdigit() and len(part) > 10:
                return part
        # Also check query params for item_id or video_id
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        for key in ("item_id", "video_id"):
            if key in qs:
                return qs[key][0]
        raise ValueError("Could not extract video ID from: " + final_url if 'final_url' in dir() else url)


# -- Share bot --
class ShareBot:
    def __init__(self, video_id, sv):
        self.video_id        = video_id
        self.share_variables = sv
        self.session         = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        )
        self.session.cookie_jar.clear()

    async def send_share(self):
        platform_    = random.choice(PLATFORMS)
        os_version_  = random.randint(1, 12)
        device_type_ = random.choice(DEVICE_TYPES)
        device_id_   = random.randint(10**18, 10**19 - 1)
        app_name_    = random.choice(["tiktok_web", "musically_go"])
        api_domain_  = random.choice(APP_DOMAINS)
        channel_     = random.choice(CHANNELS)

        headers = {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "user-agent":   random.choice(USER_AGENTS),
        }
        uri = (
            "https://" + api_domain_ + "/aweme/v1/aweme/stats/?"
            "channel=" + channel_ + "&"
            "device_type=" + device_type_ + "&"
            "device_id=" + str(device_id_) + "&"
            "os_version=" + str(os_version_) + "&"
            "version_code=220400&"
            "app_name=" + app_name_ + "&"
            "device_platform=" + platform_ + "&"
            "aid=1988"
        )
        data = "item_id=" + self.video_id + "&share_delta=1"

        try:
            response = await self.session.post(url=uri, headers=headers, data=data)
            self.share_variables.sent_requests += 1
            if response.status == 200:
                self.share_variables.successful_requests += 1
            else:
                self.share_variables.failed_requests += 1
            return response.status
        except Exception:
            self.share_variables.sent_requests += 1
            self.share_variables.failed_requests += 1
            return 0

    async def run(self, amount):
        batch_size = min(amount, 50)
        remaining = amount
        while remaining > 0:
            current_batch = min(batch_size, remaining)
            await asyncio.gather(*[self.send_share() for _ in range(current_batch)])
            remaining -= current_batch

    async def close(self):
        await self.session.close()


# -- Middleware for logging and error handling --
@web.middleware
async def request_logger_middleware(request, handler):
    logger.info(f"[{request.method}] {request.path}")
    try:
        response = await handler(request)
        logger.info(f"  [>] {response.status}")
        return response
    except web.HTTPException as ex:
        logger.warning(f"  [!] HTTP Exception: {ex.status} - {ex.reason}")
        if request.path.startswith("/api/"):
            return web.json_response({"error": ex.reason}, status=ex.status)
        raise ex
    except Exception as ex:
        logger.error(f"  [!] Server error: {str(ex)}", exc_info=True)
        if request.path.startswith("/api/"):
            return web.json_response({"error": "Internal server error: " + str(ex)}, status=500)
        raise ex


# -- Web server handlers --
async def handle_index(request):
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")

async def handle_status(request):
    data = {
        "sent": share_vars.sent_requests,
        "successful": share_vars.successful_requests,
        "failed": share_vars.failed_requests,
        "completed": share_vars.completed,
        "started": share_vars.started,
        "video_id": share_vars.video_id,
        "target": SHARE_AMOUNT,
        "url": VIDEO_URL,
        "status_msg": share_vars.status_msg,
    }
    return web.json_response(data)

async def handle_start(request):
    """Start the share bot via the web UI."""
    global VIDEO_URL, SHARE_AMOUNT
    try:
        # If already running (not yet completed), reject
        if share_vars.started and not share_vars.completed:
            return web.json_response({"error": "Already running"}, status=400)

        # Reset state for a fresh run
        share_vars.reset()

        # Allow custom URL/amount from POST body
        try:
            body = await request.json()
            logger.info(f"  [>] Body: {body}")
        except Exception as e:
            logger.warning(f"  [!] Failed to parse JSON body: {e}")
            body = {}

        if "url" in body and body["url"].strip():
            VIDEO_URL = body["url"].strip()
        if "amount" in body:
            try:
                SHARE_AMOUNT = int(body["amount"])
            except ValueError:
                pass

        asyncio.ensure_future(run_shares())
        return web.json_response({"status": "started"})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


# -- Core share logic --
async def run_shares():
    share_vars.started = True
    share_vars.status_msg = "Resolving video ID..."
    print("  [~] Resolving video ID for: " + VIDEO_URL)

    try:
        video_id = await resolve_video_id(VIDEO_URL)
    except Exception as exc:
        share_vars.status_msg = "ERROR: " + str(exc)
        share_vars.completed = True
        share_vars.started = False  # allow re-run after error
        print("  [!] " + str(exc))
        return

    share_vars.video_id = video_id
    share_vars.status_msg = "Sending shares..."
    print("  [+] Video ID: " + video_id)
    print("  [+] Sending " + str(SHARE_AMOUNT) + " shares...")

    bot = ShareBot(video_id, share_vars)
    try:
        await bot.run(SHARE_AMOUNT)
    finally:
        await bot.close()
        share_vars.completed = True
        share_vars.status_msg = "Completed!"
        print("")
        print("  [+] COMPLETED!")
        print("      Successful : " + str(share_vars.successful_requests))
        print("      Failed     : " + str(share_vars.failed_requests))
        print("      Total sent : " + str(share_vars.sent_requests))


# -- Main --
async def main():
    print("=" * 60)
    print("  [*] TikTok Share Bot - Web Dashboard")
    print("=" * 60)
    print("")

    app = web.Application(middlewares=[request_logger_middleware])
    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/start", handle_start)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    print(f"  Dashboard running at: http://localhost:8080")
    print("  Open that URL in your browser to control the bot!")
    print("")

    # Keep the server running
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("")
        print("  Stopped by user.")
        sys.exit(0)
