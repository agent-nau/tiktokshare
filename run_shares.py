"""
Runner script — resolves short TikTok URL and sends 1000 shares.
Usage: python run_shares.py
"""

import asyncio
import math
import os
import random
import ssl
import sys
import threading
import time
from urllib.parse import urlparse

import aiohttp
from pystyle import Colors, Colorate

from data.lists import PLATFORMS, DEVICE_TYPES, APP_DOMAINS, CHANNELS
from data.user_agents import USER_AGENTS

# ── SSL workaround ──────────────────────────────────────────────────────────
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# ── Configuration ───────────────────────────────────────────────────────────
VIDEO_URL    = "https://vt.tiktok.com/zs9rcfhds/"
SHARE_AMOUNT = 1000

# ── Shared state ────────────────────────────────────────────────────────────
class ShareVariables:
    sent_requests       = 0
    successful_requests = 0
    completed           = False


# ── Helper: resolve short URL to video ID ───────────────────────────────────
async def resolve_video_id(url: str) -> str:
    """Follow redirects to get the full TikTok URL, then extract the video ID."""
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        parsed = urlparse(url)
        host   = (parsed.hostname or "").lower()
        if host in ("vm.tiktok.com", "vt.tiktok.com"):
            # Follow the redirect chain to the canonical URL
            async with session.get(url, allow_redirects=True) as resp:
                final_url = str(resp.url)
            parsed = urlparse(final_url)
        parts = parsed.path.split("/")
        # canonical path is /@username/video/<id>
        for part in reversed(parts):
            if part.isdigit():
                return part
        raise ValueError(f"Could not extract video ID from: {parsed.geturl()}")


# ── Share bot ────────────────────────────────────────────────────────────────
class ShareBot:
    def __init__(self, video_id: str, share_vars: ShareVariables):
        self.video_id        = video_id
        self.share_variables = share_vars
        self.session         = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        )
        self.session.cookie_jar.clear()

    async def send_share(self) -> int:
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
            f"https://{api_domain_}/aweme/v1/aweme/stats/?"
            f"channel={channel_}&"
            f"device_type={device_type_}&"
            f"device_id={device_id_}&"
            f"os_version={os_version_}&"
            f"version_code=220400&"
            f"app_name={app_name_}&"
            f"device_platform={platform_}&"
            f"aid=1988"
        )
        data = f"item_id={self.video_id}&share_delta=1"

        response = await self.session.post(url=uri, headers=headers, data=data)
        self.share_variables.sent_requests += 1
        if response.status == 200:
            self.share_variables.successful_requests += 1
        return response.status

    async def run(self, amount: int) -> None:
        iters_  = 1
        range_  = amount
        if amount > 10000:
            iters_  = math.ceil(amount / 10000)
            range_  = 10000
        for _ in range(iters_):
            await asyncio.gather(*[self.send_share() for _ in range(range_)])

    async def close(self):
        await self.session.close()


# ── Progress reporter ─────────────────────────────────────────────────────────
def progress_thread(share_vars: ShareVariables) -> None:
    while not share_vars.completed:
        start = share_vars.sent_requests
        time.sleep(1)
        elapsed = share_vars.sent_requests - start
        print(
            f"  ✔ Successful: {share_vars.successful_requests:>5}  │  "
            f"Total sent: {share_vars.sent_requests:>5}  │  "
            f"{elapsed:>4} req/s   ",
            end="\r",
        )
    print(Colorate.Color(Colors.green, "\n\nAll done! ✅"))


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print(Colorate.Color(Colors.purple_to_blue, "TikTok Share Bot"))
    print(f"  URL    : {VIDEO_URL}")
    print(f"  Target : {SHARE_AMOUNT} shares\n")

    print("  Resolving video ID …", end=" ", flush=True)
    try:
        video_id = await resolve_video_id(VIDEO_URL)
    except Exception as exc:
        print(f"\n[ERROR] Could not resolve URL: {exc}")
        sys.exit(1)
    print(f"ID = {video_id}")

    share_vars = ShareVariables()
    bot        = ShareBot(video_id, share_vars)

    # Start progress reporter in background thread
    t = threading.Thread(target=progress_thread, args=(share_vars,), daemon=True)
    t.start()

    try:
        await bot.run(SHARE_AMOUNT)
    finally:
        await bot.close()
        share_vars.completed = True
        t.join(timeout=2)

    print(
        f"\n  Final → Successful: {share_vars.successful_requests} / "
        f"Sent: {share_vars.sent_requests}"
    )


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
        sys.exit(0)
