import json
import os
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_API_ID = int(os.environ.get("TELEGRAM_API_ID", "35009041"))
DEFAULT_API_HASH = os.environ.get("TELEGRAM_API_HASH", "c0cc7d04faca251fbb0f8739927779b1")
BOT_USERNAME = "Meeshojsoncheckerbot"


from typing import Optional, Tuple


def get_telegram_session_string() -> Optional[str]:
    # 1. Check environment variable first (preferred for Render cloud deployment)
    env_sess = os.environ.get("TELEGRAM_STRING_SESSION")
    if env_sess and env_sess.strip():
        return env_sess.strip()

    # 2. Check local session files
    candidates = [
        Path("userbot.session.txt"),
        Path(r"c:\Users\chatu\Desktop\Meesho - Arena\OTP-Gen\userbot.session.txt"),
    ]
    for p in candidates:
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return None


def refresh_via_telegram(session_data: dict, session_file_path: Optional[Path] = None, timeout: int = 30) -> dict:
    """
    Refreshes Meesho session XO token via @Meeshojsoncheckerbot using Telethon.
    Updates session_file_path if provided.
    """
    if not session_data.get("ox"):
        raise ValueError("Cannot refresh session: 'ox' refresh token is missing from JSON.")

    session_str = get_telegram_session_string()
    if not session_str:
        raise FileNotFoundError("Telegram session not found. Set TELEGRAM_STRING_SESSION env var or provide userbot.session.txt.")

    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(session_str), DEFAULT_API_ID, DEFAULT_API_HASH)

    print("[Telegram Refresh] Connecting to Telegram userbot...")
    with client:
        bot = client.get_entity(BOT_USERNAME)
        print(f"[Telegram Refresh] Opening conversation with @{BOT_USERNAME}...")
        client.send_message(bot, "/start")
        time.sleep(2)

        # Look for 'JSON Refresh' button
        msgs = client.get_messages(bot, limit=5)
        button_clicked = False
        for m in msgs:
            if m.buttons:
                for r_idx, r in enumerate(m.buttons):
                    for c_idx, b in enumerate(r):
                        if "JSON Refresh" in b.text or "Refresh" in b.text:
                            print(f"[Telegram Refresh] Clicking '{b.text}' button...")
                            m.click(r_idx, c_idx)
                            button_clicked = True
                            time.sleep(2)
                            break
                    if button_clicked:
                        break
            if button_clicked:
                break

        print("[Telegram Refresh] Sending account JSON to bot...")
        json_payload = json.dumps(session_data)
        sent_msg = client.send_message(bot, json_payload)

        # Wait for reply with refreshed content
        start_time = time.time()
        refreshed_data = None

        while time.time() - start_time < timeout:
            time.sleep(2)
            replies = client.get_messages(bot, limit=5)
            for reply in replies:
                if reply.id <= sent_msg.id:
                    continue

                # Case A: Bot sent a document file with refreshed JSON
                if reply.file and ("refreshed" in (reply.file.name or "").lower() or (reply.file.name or "").endswith((".json", ".txt"))):
                    print(f"[Telegram Refresh] Received refreshed file: {reply.file.name}")
                    content_bytes = client.download_media(reply, bytes)
                    if content_bytes:
                        try:
                            refreshed_data = json.loads(content_bytes.decode("utf-8"))
                            break
                        except Exception:
                            pass

                # Case B: Bot sent JSON directly in text
                if reply.text and ('"xo"' in reply.text or "eyJ0eXBlIjoiY29tcG9zaXRlIn0=" in reply.text):
                    text = reply.text.strip()
                    # extract json block if wrapped in markdown
                    if "```" in text:
                        text = text.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]
                    try:
                        refreshed_data = json.loads(text.strip())
                        break
                    except Exception:
                        pass

            if refreshed_data:
                break

        if not refreshed_data:
            raise TimeoutError("Timed out waiting for @Meeshojsoncheckerbot to return refreshed JSON.")

        print(f"[Telegram Refresh] Successfully received refreshed XO token for mobile: {refreshed_data.get('mobile')}")

        # Update original session data
        session_data["xo"] = refreshed_data.get("xo")
        if "ox" in refreshed_data:
            session_data["ox"] = refreshed_data.get("ox")
        if "user_id" in refreshed_data:
            session_data["user_id"] = refreshed_data.get("user_id")

        if session_file_path:
            p = Path(session_file_path)
            p.write_text(json.dumps(session_data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[Telegram Refresh] Updated session file: {p.resolve()}")

        return session_data


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "meesho_account_8869049741.json"
    p = Path(target)
    if not p.is_file():
        print(f"File not found: {p}")
        sys.exit(1)

    data = json.loads(p.read_text(encoding="utf-8"))
    print(f"Refreshing {p.name}...")
    refresh_via_telegram(data, p)
    print("Done!")
