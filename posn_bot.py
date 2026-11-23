import hashlib
import json
import os
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= CONFIGURATION =================
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or "PASTE_YOUR_DISCORD_WEBHOOK_URL_HERE"
TARGET_URL = "https://www.sc.su.ac.th/"
BOT_NAME = "POSNBot"

CHECK_INTERVAL = 30       # Check every 30 seconds
MAX_RUNTIME = 13.5 * 60   # Loop for 13.5 minutes per GitHub Action run

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "posn_state.json")
# =================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
    )
}


def fetch_page(url: str) -> str:
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
    except requests.exceptions.SSLError:
        res = requests.get(url, headers=HEADERS, timeout=15, verify=False)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    return res.text


def parse_page(html: str, base_url: str) -> tuple[dict[str, str], str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta"]):
        tag.decompose()

    links: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full_url = urljoin(base_url, href)
        title = " ".join(a.get_text().split())
        if len(title) >= 4:
            links[full_url] = title

    clean_text = " ".join(soup.get_text().split())
    text_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
    return links, text_hash


def load_state() -> dict | None:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(links: dict[str, str], text_hash: str) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"links": links, "text_hash": text_hash}, f, ensure_ascii=False, indent=2)


def send_discord_notification(new_links: list[tuple[str, str]], page_changed_only: bool = False) -> None:
    if new_links:
        lines = [f"• **[{title}]({url})**" for url, title in new_links[:10]]
        if len(new_links) > 10:
            lines.append(f"*...and {len(new_links) - 10} more new links.*")
        description = "\n".join(lines)
        title = f"📢 New Update on sc.su.ac.th ({len(new_links)} new item{'s' if len(new_links) > 1 else ''})"
    elif page_changed_only:
        description = f"Content on **{TARGET_URL}** was modified, though no new links were added."
        title = "🔄 Page Content Updated on sc.su.ac.th"
    else:
        return

    payload = {
        "username": BOT_NAME,
        "embeds": [
            {
                "title": title,
                "url": TARGET_URL,
                "description": description,
                "color": 0x00A86B,
                "footer": {"text": f"Checked at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"},
            }
        ],
    }

    res = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    res.raise_for_status()


def run_loop() -> None:
    if "PASTE_YOUR_DISCORD_WEBHOOK_URL_HERE" in WEBHOOK_URL:
        raise ValueError("Set your WEBHOOK_URL first.")

    state = load_state()
    start_time = time.time()

    while True:
        try:
            html = fetch_page(TARGET_URL)
            current_links, current_hash = parse_page(html, TARGET_URL)

            if state is None:
                save_state(current_links, current_hash)
                state = {"links": current_links, "text_hash": current_hash}
                print(f"[{datetime.now():%H:%M:%S}] Baseline saved ({len(current_links)} links indexed).")
            else:
                old_links = state.get("links", {})
                new_items = [(url, title) for url, title in current_links.items() if url not in old_links]

                if new_items:
                    print(f"[{datetime.now():%H:%M:%S}] Found {len(new_items)} new link(s)! Sending alert...")
                    send_discord_notification(new_items)
                    save_state(current_links, current_hash)
                    state = {"links": current_links, "text_hash": current_hash}
                elif current_hash != state.get("text_hash"):
                    print(f"[{datetime.now():%H:%M:%S}] Page text changed! Sending alert...")
                    send_discord_notification([], page_changed_only=True)
                    save_state(current_links, current_hash)
                    state = {"links": current_links, "text_hash": current_hash}
                else:
                    print(f"[{datetime.now():%H:%M:%S}] No changes.")

        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] Check failed (will retry in {CHECK_INTERVAL}s): {e}")

        if (time.time() - start_time) + CHECK_INTERVAL >= MAX_RUNTIME:
            print(f"[{datetime.now():%H:%M:%S}] Session complete. Saving state...")
            break

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run_loop()
