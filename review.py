from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse

import requests

try:
    from refresh_session import refresh_via_telegram
except ImportError:
    refresh_via_telegram = None

try:
    import otpless_auth
except ImportError:
    otpless_auth = None

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ------------------------------------------------------------
# Defaults & Constants
# ------------------------------------------------------------
DEFAULT_API_HOST = "https://prod.meeshoapi.com"
DEFAULT_AUTHORIZATION = "32c4d8137cn9eb493a1921f203173080"
DEFAULT_SHIELD_SESSION_ID = "1a047084893d4f8fb23f1adebb000cf8"
APP_VERSION = "29.5"
APP_VERSION_CODE = "868"
APP_SDK_VERSION = "34"

OUTPUT_DIR = Path("review_output")
TIMEOUT = 25


class MeeshoSession:
    """Manages Meesho authenticated session, client headers, and token refresh."""

    def __init__(self, session_path: Path, session_data: dict):
        self.session_path = session_path
        self.data = session_data
        self.client, self.base_url = self._build_client()

    def _build_client(self) -> Tuple[requests.Session, str]:
        identity = self.data.get("identity") or {}

        user_id = self.data.get("user_id") or ""
        phone = self.data.get("phone") or (f"+91{self.data['mobile']}" if self.data.get("mobile") else "")
        u_token = base64.b64encode(phone.encode()).decode() if phone else ""

        auth = self.data.get("authorization") or identity.get("authorization") or DEFAULT_AUTHORIZATION
        shield_id = self.data.get("shield_session_id") or identity.get("shield_session_id") or DEFAULT_SHIELD_SESSION_ID
        instance_id = str(self.data.get("instance_id") or identity.get("instance_id") or uuid.uuid4().hex)
        app_session_id = str(identity.get("app_session_id") or uuid.uuid4().hex)
        gaid = str(self.data.get("gaid") or identity.get("gaid") or "")
        fcm_token = str(self.data.get("fcm_token") or identity.get("fcm_token") or "")

        headers = {
            "Authorization": auth,
            "App-Version": str(self.data.get("app_version", APP_VERSION)),
            "App-Version-Code": str(self.data.get("app_version_code", APP_VERSION_CODE)),
            "Instance-Id": instance_id,
            "Country-Iso": "in",
            "Application-Id": "com.meesho.supply",
            "App-Session-Id": app_session_id,
            "App-Sdk-Version": APP_SDK_VERSION,
            "App-Client-Id": "android",
            "Shield-Session-Id": shield_id,
            "Xo": str(self.data.get("xo", "")),
            "App-User-Id": str(user_id),
            "U-Token": u_token,
            "Meesho-User-Context": "logged_in" if self.data.get("xo") else "anonymous",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "okhttp/4.9.0",
        }

        if gaid:
            headers["App-Gaid"] = gaid
        if fcm_token:
            headers["App-Fcm-Token"] = fcm_token

        client = requests.Session()
        client.headers.update(headers)
        client.verify = True
        client.max_redirects = 0

        api_host = self.data.get("api_host") or DEFAULT_API_HOST
        if not api_host.startswith("http"):
            api_host = f"https://{api_host}"

        return client, api_host

    def update_tokens(self, new_xo: str, new_ox: Optional[str] = None):
        """Update session headers and save to JSON file."""
        self.data["xo"] = new_xo
        if new_ox:
            self.data["ox"] = new_ox

        self.client.headers["Xo"] = str(new_xo)
        phone = self.data.get("phone") or (f"+91{self.data['mobile']}" if self.data.get("mobile") else "")
        if phone:
            self.client.headers["U-Token"] = base64.b64encode(phone.encode()).decode()
        self.client.headers["Meesho-User-Context"] = "logged_in"

        self.session_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  [+] Session file updated: {self.session_path.resolve()}")

    def refresh(self) -> bool:
        """Attempt session refresh via Telegram bot (using ox) or fallback to Otpless."""
        print("\n" + "-" * 50)
        print("[Auth Refresh] Attempting session refresh...")

        # Option A: Telegram Bot Refresh using 'ox' token
        if self.data.get("ox") and refresh_via_telegram:
            try:
                print("  -> Attempting refresh via Telegram (@Meeshojsoncheckerbot)...")
                new_data = refresh_via_telegram(self.data, self.session_path)
                self.update_tokens(new_data["xo"], new_data.get("ox"))
                print("  [+] Telegram refresh successful! Fresh XO token acquired.")
                print("-" * 50 + "\n")
                return True
            except Exception as exc:
                print(f"  [-] Telegram refresh failed: {exc}")

        # Option B: Fallback to Otpless OTP verification
        mobile = self.data.get("mobile") or (self.data.get("phone", "").lstrip("+91"))
        if mobile and otpless_auth:
            try:
                print(f"  -> Attempting Otpless OTP flow for +91{mobile}...")
                ctx = otpless_auth.send_otp(mobile)
                otp = input(f"Enter 6-digit OTP sent to +91{mobile}: ").strip()
                user_info, xoox = otpless_auth.verify_otp_and_login(ctx, otp, self.data)
                if "user_id" in user_info:
                    self.data["user_id"] = user_info["user_id"]
                    self.client.headers["App-User-Id"] = str(user_info["user_id"])
                self.update_tokens(xoox["xo"], xoox.get("ox"))
                print("  [+] Otpless login successful!")
                print("-" * 50 + "\n")
                return True
            except Exception as exc:
                print(f"  [-] Otpless OTP login failed: {exc}")

        print("  [-] Automatic refresh failed. Unable to acquire fresh session.")
        print("-" * 50 + "\n")
        return False


def save_json(name: str, data: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / name
    out_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  [+] Saved {out_path}")
    return out_path


def request_json(
    sess: MeeshoSession,
    method: str,
    path: str,
    payload: dict = None,
    auto_retry: bool = True,
) -> dict:
    url = f"{sess.base_url}{path}"
    response = sess.client.request(
        method=method,
        url=url,
        json=payload,
        timeout=TIMEOUT,
        allow_redirects=False,
    )

    if response.status_code == 401:
        proxy_code = response.headers.get("x-proxy-auth-failure-code", "")

        # Auto-refresh session if proxy auth code indicates invalid/revoked/expired token
        if auto_retry and proxy_code in ("1007", "1014", "1003", "1010"):
            print(f"\n[Auth Notice] Encountered 401 Unauthorized (Proxy Code: {proxy_code}) on {path}.")
            if sess.refresh():
                print(f"  -> Retrying {method} {path} with refreshed session...")
                return request_json(sess, method, path, payload, auto_retry=False)

        try:
            err = response.json()
        except Exception:
            err = response.text

        detail = f"HTTP 401 Unauthorized for {path}: {err}"
        if proxy_code:
            detail += f" [Proxy Auth Code: {proxy_code}]"
            if proxy_code == "1007":
                detail += (
                    "\n  -> Explanation: Code 1007 indicates the session ('xo') was invalidated on Meesho's "
                    "backend session store (e.g. replaced by a newer login, logged out, or revoked)."
                )
            elif proxy_code == "1014":
                detail += "\n  -> Explanation: Code 1014 indicates the session JWT token has expired."
            elif proxy_code == "1003":
                detail += "\n  -> Explanation: Code 1003 indicates a malformed or corrupted session token."
            elif proxy_code == "1010":
                detail += "\n  -> Explanation: Code 1010 indicates an empty inner session token."
        raise PermissionError(detail)

    response.raise_for_status()

    if not response.content:
        return {}

    try:
        return response.json()
    except ValueError:
        raise RuntimeError(f"Expected JSON from {path}, got non-JSON response.")


def perform_login(sess: MeeshoSession):
    """Perform login verification or validate existing logged-in session."""
    print("Checking login flow...")

    if "otpless" in sess.data or "login_type" in sess.data:
        print("  -> Performing POST /api/2.0/user/login...")
        sess.client.headers["Meesho-User-Context"] = "anonymous"
        login_payload = {
            "login_type": sess.data.get("login_type", "otpless"),
            "otpless": sess.data.get("otpless", {}),
            "ga_id": sess.data.get("gaid") or sess.data.get("identity", {}).get("gaid", ""),
        }
        resp = request_json(sess, "POST", "/api/2.0/user/login", login_payload)
        save_json("login_response.json", resp)

        if "user" in resp:
            sess.data["user_id"] = resp["user"].get("user_id")
            sess.data["phone"] = resp["user"].get("phone")
        if "xoox" in resp:
            sess.update_tokens(resp["xoox"].get("xo"), resp["xoox"].get("ox"))

        print(f"  [+] Login successful for user_id: {sess.data['user_id']}")
    else:
        # Validate existing logged in session
        print("  -> Validating existing session via /api/1.0/user-profile...")
        profile = request_json(sess, "GET", "/api/1.0/user-profile")
        save_json("user_profile.json", profile)
        print(f"  [+] Session verified for user_id: {profile.get('userId', sess.data.get('user_id'))}")


def discover_order_pair(orders_response: dict) -> Tuple[int, int, str, str]:
    """Find a delivered/ratable order and sub-order from the orders response."""
    sub_orders = orders_response.get("sub_order_list") or []

    # First priority: find a delivered order
    for item in sub_orders:
        if item.get("sub_order_status") == "STATUS_ID_DELIVERED":
            order_id = item.get("order_id")
            sub_order_id = item.get("sub_order_id")
            order_num = item.get("order_num") or str(order_id)
            sub_order_num = item.get("sub_order_num") or f"{order_num}_1"
            return order_id, sub_order_id, str(order_num), str(sub_order_num)

    # Fallback to the first available order
    if sub_orders:
        item = sub_orders[0]
        order_id = item.get("order_id")
        sub_order_id = item.get("sub_order_id")
        order_num = item.get("order_num") or str(order_id)
        sub_order_num = item.get("sub_order_num") or f"{order_num}_1"
        return order_id, sub_order_id, str(order_num), str(sub_order_num)

    raise RuntimeError("No orders found in user account.")


def main():
    parser = argparse.ArgumentParser(description="Meesho Rating & Review Automation")
    parser.add_argument("session_file", nargs="?", default=None, help="Path to account session JSON file")
    parser.add_argument("--refresh", action="store_true", help="Proactively refresh session before executing flow")
    args = parser.parse_args()

    # Determine session JSON path
    if args.session_file:
        session_path = Path(args.session_file)
    else:
        candidates = [Path("meesho_account_8869049741.json"), Path("7977748514.json")]
        session_path = next((p for p in candidates if p.is_file()), candidates[0])

    if not session_path.is_file():
        raise FileNotFoundError(f"Session JSON file not found: {session_path}")

    session_data = json.loads(session_path.read_text(encoding="utf-8"))
    print(f"Loaded session JSON from: {session_path}")

    sess = MeeshoSession(session_path, session_data)

    if args.refresh:
        sess.refresh()

    # 1. Login or verify existing session
    perform_login(sess)
    user_id = sess.data["user_id"]

    # 2. Check pending ratings
    print("\n[Step 1] Checking pending ratings...")
    pending = request_json(sess, "GET", "/api/1.0/suborders/ratings/pending")
    save_json("pending_ratings.json", pending)

    # 3. Fetch orders
    print("\n[Step 2] Fetching user orders...")
    orders_payload = {
        "limit": 10,
        "cursor": None,
        "query": None,
        "filters": {
            "sub_order_status": [0],
            "sub_order_created": None,
        },
        "user_id": user_id,
    }
    orders = request_json(sess, "POST", "/api/3.0/user/orders", orders_payload)
    save_json("orders.json", orders)

    order_id, sub_order_id, order_num, sub_order_num = discover_order_pair(orders)
    print(f"  [+] Target Order: {order_id} (num: {order_num}), Sub-order: {sub_order_id} (num: {sub_order_num})")

    # 4. Fetch order details
    print("\n[Step 3] Fetching order details...")
    order_details = request_json(
        sess,
        "POST",
        "/api/3.0/user/order-details",
        {
            "order_num": order_num,
            "sub_order_num": sub_order_num,
            "user_id": user_id,
        },
    )
    save_json("order_details.json", order_details)

    # 5. Check rating status
    print("\n[Step 4] Checking rating status for sub-order...")
    rating_status = request_json(sess, "GET", f"/api/1.0/user/ratings/fetch/{sub_order_num}")
    save_json("rating_status.json", rating_status)

    # Rating configuration from session or default
    rating_stars = int(sess.data.get("rating", 5))
    comments_text = sess.data.get("comments", "good and nice")

    # 6. Submit initial star rating
    print(f"\n[Step 5] Submitting star rating ({rating_stars} stars)...")
    rating_resp = request_json(
        sess,
        "POST",
        f"/api/3.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings",
        {
            "order_detail_rating": {
                "rating": rating_stars,
            },
            "user_id": user_id,
        },
    )
    save_json("rating_initial.json", rating_resp)

    rating_id = rating_resp.get("order_detail_rating", {}).get("id")
    print(f"  [+] Rating ID: {rating_id}")

    # 7. Fetch rating flow metadata
    print("\n[Step 6] Fetching rating flow metadata...")
    rating_new = request_json(
        sess,
        "GET",
        f"/api/2.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings/new",
    )
    save_json("rating_flow.json", rating_new)

    # 8. Fetch current rating by ID
    if rating_id:
        print(f"\n[Step 7] Fetching rating details for ID {rating_id}...")
        rating_details = request_json(
            sess,
            "GET",
            f"/api/3.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings/{rating_id}",
        )
        save_json("rating_details.json", rating_details)

        # 9. Fetch product review attributes
        print("\n[Step 8] Fetching review product attributes...")
        attributes_resp = request_json(
            sess,
            "POST",
            "/api/v1/review/product-attributes",
            {
                "review_id": rating_id,
                "fetch_response": True,
                "user_id": user_id,
            },
        )
        save_json("product_attributes.json", attributes_resp)

        # 10. Submit attribute ratings
        print("\n[Step 9] Submitting attribute ratings...")
        attributes_list = attributes_resp.get("attributes") or []
        scale_type = attributes_resp.get("scale", {}).get("type", 5)

        attr_payload = {
            "order_detail_rating": {
                "attribute_ratings": {
                    "attributes": [
                        {"attribute_id": attr["id"], "rating": rating_stars}
                        for attr in attributes_list
                    ],
                    "scale": scale_type,
                },
                "rating": rating_stars,
            },
            "user_id": user_id,
        }
        attr_rating_resp = request_json(
            sess,
            "POST",
            f"/api/3.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings/{rating_id}",
            attr_payload,
        )
        save_json("rating_attributes_resp.json", attr_rating_resp)

        # 11. Submit review comments / preview
        print("\n[Step 10] Submitting review preview with comments...")
        review_preview_payload = {
            "add_images": [],
            "add_videos": [],
            "delete_image_ids": [],
            "delete_video_ids": [],
            "order_detail_rating": {
                "images": [],
                "videos": [],
                "selected_option_ids": [],
                "rating": rating_stars,
                "selected_question_id": 2,
                "id": rating_id,
                "comments": comments_text,
            },
            "user_id": user_id,
        }
        review_preview_resp = request_json(
            sess,
            "POST",
            f"/api/3.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings/{rating_id}",
            review_preview_payload,
        )
        save_json("review_preview.json", review_preview_resp)

    # 12. Check pending reviews
    print("\n[Step 11] Checking pending reviews list...")
    reviews_pending = request_json(
        sess,
        "POST",
        "/api/1.0/reviews/pending",
        {
            "offset": 0,
            "limit": 20,
            "user_id": user_id,
        },
    )
    save_json("reviews_pending.json", reviews_pending)

    print("\n" + "=" * 60)
    print("SUCCESS: Complete rating and review flow executed successfully!")
    print(f"Order ID: {order_id}")
    print(f"Sub-order ID: {sub_order_id}")
    print(f"Rating ID: {rating_id}")
    print(f"Rating: {rating_stars} stars")
    print(f"Comments: {comments_text}")
    print(f"Output files saved to: {OUTPUT_DIR.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except PermissionError as exc:
        print(f"\n[Auth Error] {exc}")
        sys.exit(1)
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        text = getattr(getattr(exc, "response", None), "text", None)
        print(f"\n[HTTP Error] Request failed. Status: {status or 'unavailable'}. Details: {text or exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[Error] {exc}")
        sys.exit(1)
