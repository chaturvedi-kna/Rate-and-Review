import base64
import json
import uuid
from typing import Dict, Any, Tuple, Optional, List
import requests

try:
    from refresh_session import refresh_via_telegram
except ImportError:
    refresh_via_telegram = None

DEFAULT_API_HOST = "https://prod.meeshoapi.com"
DEFAULT_AUTHORIZATION = "32c4d8137cn9eb493a1921f203173080"
DEFAULT_SHIELD_SESSION_ID = "1a047084893d4f8fb23f1adebb000cf8"
APP_VERSION = "29.5"
APP_VERSION_CODE = "868"
APP_SDK_VERSION = "34"
TIMEOUT = 20


def make_client(session_data: dict) -> Tuple[requests.Session, str]:
    identity = session_data.get("identity") or {}

    user_id = session_data.get("user_id") or ""
    phone = session_data.get("phone") or (f"+91{session_data['mobile']}" if session_data.get("mobile") else "")
    u_token = base64.b64encode(phone.encode()).decode() if phone else ""

    auth = session_data.get("authorization") or identity.get("authorization") or DEFAULT_AUTHORIZATION
    shield_id = session_data.get("shield_session_id") or identity.get("shield_session_id") or DEFAULT_SHIELD_SESSION_ID
    instance_id = str(session_data.get("instance_id") or identity.get("instance_id") or uuid.uuid4().hex)
    app_session_id = str(identity.get("app_session_id") or uuid.uuid4().hex)
    gaid = str(session_data.get("gaid") or identity.get("gaid") or "")
    fcm_token = str(session_data.get("fcm_token") or identity.get("fcm_token") or "")

    headers = {
        "Authorization": auth,
        "App-Version": str(session_data.get("app_version", APP_VERSION)),
        "App-Version-Code": str(session_data.get("app_version_code", APP_VERSION_CODE)),
        "Instance-Id": instance_id,
        "Country-Iso": "in",
        "Application-Id": "com.meesho.supply",
        "App-Session-Id": app_session_id,
        "App-Sdk-Version": APP_SDK_VERSION,
        "App-Client-Id": "android",
        "Shield-Session-Id": shield_id,
        "Xo": str(session_data.get("xo", "")),
        "App-User-Id": str(user_id),
        "U-Token": u_token,
        "Meesho-User-Context": "logged_in" if session_data.get("xo") else "anonymous",
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

    api_host = session_data.get("api_host") or DEFAULT_API_HOST
    if not api_host.startswith("http"):
        api_host = f"https://{api_host}"

    # Indian Proxy routing for Meesho endpoints
    try:
        from proxy_manager import get_meesho_proxies
        import db
        proxy_conf = db.get_setting("meesho_proxy")
        proxies = get_meesho_proxies(proxy_conf)
        if proxies:
            client.proxies = proxies
    except Exception:
        pass

    return client, api_host


def validate_account(session_data: dict) -> Dict[str, Any]:
    """Checks validity of the account session and fetches order status."""
    client, base_url = make_client(session_data)
    result = {
        "valid": False,
        "status": "UNKNOWN",
        "proxy_code": None,
        "user_id": session_data.get("user_id"),
        "mobile": session_data.get("mobile"),
        "ratable_order": None,
        "order_count": 0,
        "error": None,
    }

    # Step 1: Check user profile
    try:
        resp = proxy_manager.request_with_retry(client, "GET", f"{base_url}/api/1.0/user-profile", timeout=TIMEOUT)
        proxy_code = resp.headers.get("x-proxy-auth-failure-code")
        result["proxy_code"] = proxy_code

        if resp.status_code == 401:
            if proxy_code == "1014":
                result["status"] = "EXPIRED_1014"
                result["error"] = "JWT Token expired (Proxy Code 1014)"
            elif proxy_code == "1007":
                result["status"] = "REVOKED_1007"
                result["error"] = "Session revoked/replaced on server (Proxy Code 1007)"
            else:
                result["status"] = "UNAUTHORIZED_401"
                result["error"] = f"Unauthorized (Proxy Code {proxy_code})"
            return result

        resp.raise_for_status()
        profile_data = resp.json()
        result["valid"] = True
        result["status"] = "ACTIVE"
        if profile_data.get("userId"):
            result["user_id"] = profile_data["userId"]
            session_data["user_id"] = profile_data["userId"]

    except requests.RequestException as e:
        result["status"] = "ERROR"
        result["error"] = str(e)
        return result

    # Step 2: Fetch orders to discover ratable orders
    try:
        user_id = result["user_id"]
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
        r_orders = proxy_manager.request_with_retry(client, "POST", f"{base_url}/api/3.0/user/orders", json=orders_payload, timeout=TIMEOUT)
        if r_orders.status_code == 200:
            orders_data = r_orders.json()
            sub_orders = orders_data.get("sub_order_list") or []
            result["order_count"] = len(sub_orders)

            for item in sub_orders:
                status_id = item.get("sub_order_status")
                order_id = item.get("order_id")
                sub_order_id = item.get("sub_order_id")
                order_num = str(item.get("order_num") or order_id)
                sub_order_num = str(item.get("sub_order_num") or f"{order_num}_1")
                product_title = item.get("product_title") or item.get("name") or "Meesho Product"

                if status_id == "STATUS_ID_DELIVERED" and not result["ratable_order"]:
                    result["ratable_order"] = {
                        "order_id": order_id,
                        "sub_order_id": sub_order_id,
                        "order_num": order_num,
                        "sub_order_num": sub_order_num,
                        "status": status_id,
                        "title": product_title,
                    }

            if not result["ratable_order"] and sub_orders:
                item = sub_orders[0]
                result["ratable_order"] = {
                    "order_id": item.get("order_id"),
                    "sub_order_id": item.get("sub_order_id"),
                    "order_num": str(item.get("order_num") or item.get("order_id")),
                    "sub_order_num": str(item.get("sub_order_num") or f"{item.get('order_id')}_1"),
                    "status": item.get("sub_order_status"),
                    "title": item.get("product_title") or "Meesho Product",
                }

    except Exception:
        pass

    return result


def refresh_account_tokens(session_data: dict, session_path=None) -> Dict[str, Any]:
    """Refreshes XO using Telegram userbot integration with OX."""
    if not session_data.get("ox"):
        return {"success": False, "error": "Account JSON is missing 'ox' refresh token"}

    if not refresh_via_telegram:
        return {"success": False, "error": "Telegram refresh integration not initialized"}

    try:
        updated = refresh_via_telegram(session_data, session_path)
        return {"success": True, "xo": updated.get("xo"), "ox": updated.get("ox")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def submit_review_full(
    session_data: dict,
    rating_stars: int = 5,
    comments_text: str = "Very good quality, fabric is soft and comfortable. Value for money!",
    auto_refresh: bool = True,
    log_callback=None,
) -> Dict[str, Any]:
    """
    Executes the full 11-step Meesho rating and review flow.
    If 401 is encountered and auto_refresh is True, automatically refreshes session and retries!
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg)

    client, base_url = make_client(session_data)
    user_id = session_data.get("user_id")

    def api_call(method: str, path: str, payload: dict = None, allow_retry: bool = True) -> dict:
        url = f"{base_url}{path}"
        r = proxy_manager.request_with_retry(
            session=client,
            method=method,
            url=url,
            json=payload,
            timeout=TIMEOUT,
            log_callback=log,
        )

        if r.status_code == 401 and allow_retry and auto_refresh:
            p_code = r.headers.get("x-proxy-auth-failure-code", "")
            log(f"  [!] HTTP 401 (Proxy Code: {p_code}) on {path}. Triggering auto-refresh...")
            ref_res = refresh_account_tokens(session_data)
            if ref_res.get("success"):
                client.headers["Xo"] = str(session_data["xo"])
                log("  [+] Token refreshed successfully! Retrying request...")
                return api_call(method, path, payload, allow_retry=False)
            else:
                log(f"  [-] Auto-refresh failed: {ref_res.get('error')}")

        if r.status_code == 401:
            p_code = r.headers.get("x-proxy-auth-failure-code", "")
            raise PermissionError(f"HTTP 401 on {path} (Proxy Code: {p_code}): {r.text}")

        r.raise_for_status()
        return r.json() if r.content else {}

    try:
        # Step 0: Check profile & user_id
        log(f"[{session_data.get('mobile')}] Step 0: Verifying profile...")
        profile = api_call("GET", "/api/1.0/user-profile")
        if profile.get("userId"):
            user_id = profile["userId"]
            session_data["user_id"] = user_id
            client.headers["App-User-Id"] = str(user_id)

        # Step 1: Pending ratings
        log(f"[{session_data.get('mobile')}] Step 1: Checking pending ratings...")
        api_call("GET", "/api/1.0/suborders/ratings/pending")

        # Step 2: Fetch orders to discover target delivered order
        log(f"[{session_data.get('mobile')}] Step 2: Discovering target order...")
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
        orders = api_call("POST", "/api/3.0/user/orders", orders_payload)
        sub_orders = orders.get("sub_order_list") or []
        if not sub_orders:
            return {"success": False, "error": "No orders found in account to rate."}

        # Select delivered order
        target = next((item for item in sub_orders if item.get("sub_order_status") == "STATUS_ID_DELIVERED"), sub_orders[0])
        order_id = target.get("order_id")
        sub_order_id = target.get("sub_order_id")
        order_num = str(target.get("order_num") or order_id)
        sub_order_num = str(target.get("sub_order_num") or f"{order_num}_1")

        log(f"[{session_data.get('mobile')}] Selected Order: {order_id}, Sub-order: {sub_order_id}")

        # Step 3: Order details
        log(f"[{session_data.get('mobile')}] Step 3: Fetching order details...")
        api_call("POST", "/api/3.0/user/order-details", {
            "order_num": order_num,
            "sub_order_num": sub_order_num,
            "user_id": user_id,
        })

        # Step 4: Rating status fetch
        log(f"[{session_data.get('mobile')}] Step 4: Checking rating status...")
        api_call("GET", f"/api/1.0/user/ratings/fetch/{sub_order_num}")

        # Step 5: Submit Star Rating
        log(f"[{session_data.get('mobile')}] Step 5: Submitting star rating ({rating_stars} stars)...")
        initial_rating = api_call("POST", f"/api/3.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings", {
            "order_detail_rating": {"rating": rating_stars},
            "user_id": user_id,
        })
        rating_id = initial_rating.get("order_detail_rating", {}).get("id")
        log(f"[{session_data.get('mobile')}] Rating Created! ID: {rating_id}")

        # Step 6: Rating flow metadata
        log(f"[{session_data.get('mobile')}] Step 6: Fetching rating flow...")
        api_call("GET", f"/api/2.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings/new")

        # Step 7: Rating details by ID
        if rating_id:
            log(f"[{session_data.get('mobile')}] Step 7: Fetching rating details...")
            api_call("GET", f"/api/3.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings/{rating_id}")

            # Step 8: Fetch product attributes
            log(f"[{session_data.get('mobile')}] Step 8: Fetching review attributes...")
            attr_resp = api_call("POST", "/api/v1/review/product-attributes", {
                "review_id": rating_id,
                "fetch_response": True,
                "user_id": user_id,
            })

            # Step 9: Submit Attribute ratings
            log(f"[{session_data.get('mobile')}] Step 9: Submitting attribute ratings...")
            attr_list = attr_resp.get("attributes") or []
            scale_type = attr_resp.get("scale", {}).get("type", 5)
            api_call("POST", f"/api/3.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings/{rating_id}", {
                "order_detail_rating": {
                    "attribute_ratings": {
                        "attributes": [{"attribute_id": a["id"], "rating": rating_stars} for a in attr_list],
                        "scale": scale_type,
                    },
                    "rating": rating_stars,
                },
                "user_id": user_id,
            })

            # Step 10: Submit Review comments / preview (Final Review Submission)
            log(f"[{session_data.get('mobile')}] Step 10: Submitting final review comments: \"{comments_text}\"...")
            api_call("POST", f"/api/3.0/orders/{order_id}/sub-orders/{sub_order_id}/ratings/{rating_id}", {
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
            })

        # Step 11: Refresh pending reviews
        log(f"[{session_data.get('mobile')}] Step 11: Refreshing pending reviews...")
        api_call("POST", "/api/1.0/reviews/pending", {
            "offset": 0,
            "limit": 20,
            "user_id": user_id,
        })

        log(f"[{session_data.get('mobile')}] COMPLETE! Review successfully published for Order {order_id}!")
        return {
            "success": True,
            "order_id": order_id,
            "sub_order_id": sub_order_id,
            "rating_id": rating_id,
            "rating": rating_stars,
            "comments": comments_text,
        }

    except Exception as exc:
        log(f"[{session_data.get('mobile')}] Review flow failed: {exc}")
        return {"success": False, "error": str(exc)}

