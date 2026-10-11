import json
import re
import base64
from typing import List, Dict, Any, Optional, Tuple


import time
from datetime import datetime


def extract_user_id_from_xo(xo_str: str) -> int:
    """Extract user_id from the inner JWT payload inside Meesho's composite XO token."""
    try:
        parts = xo_str.split(".")
        if len(parts) < 2:
            return 0
        payload_b64 = parts[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        data = json.loads(base64.b64decode(payload_b64))

        jwt_str = data.get("jwt", "")
        jwt_parts = jwt_str.split(".")
        if len(jwt_parts) < 2:
            return 0
        jwt_payload_b64 = jwt_parts[1] + "=" * ((4 - len(jwt_parts[1]) % 4) % 4)
        jwt_data = json.loads(base64.urlsafe_b64decode(jwt_payload_b64))
        return int(jwt_data.get("https://meesho.com/user_id", 0))
    except Exception:
        return 0


def get_token_expiry(xo_str: str) -> Optional[int]:
    """Extracts expiration timestamp (Unix epoch) from the inner JWT payload inside Meesho's composite XO token."""
    try:
        parts = xo_str.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        data = json.loads(base64.b64decode(payload_b64))

        jwt_str = data.get("jwt", "")
        jwt_parts = jwt_str.split(".")
        if len(jwt_parts) < 2:
            return None
        jwt_payload_b64 = jwt_parts[1] + "=" * ((4 - len(jwt_parts[1]) % 4) % 4)
        jwt_data = json.loads(base64.urlsafe_b64decode(jwt_payload_b64))
        exp = jwt_data.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def is_token_expired(xo_str: str) -> Tuple[bool, Optional[int]]:
    """Checks whether token is expired. Returns (is_expired, exp_timestamp)."""
    exp = get_token_expiry(xo_str)
    if exp is not None:
        now = time.time()
        return (now >= exp, exp)
    return (False, None)


def parse_multi_jsons(raw_text: str) -> List[Dict[str, Any]]:
    """
    Parses any text input containing Meesho JSON account objects.
    Supports:
      - Standard JSON arrays: [ {...}, {...} ]
      - Concatenated JSON objects: {...} {...}
      - Line-separated JSONs (NDJSON / JSONL)
      - Space/tab/comma-separated JSON objects
      - Partial JSONs containing at least 'mobile' and 'xo'
    """
    text = raw_text.strip()
    if not text:
        return []

    results = []

    # Attempt 1: Direct standard JSON load
    try:
        loaded = json.loads(text)
        if isinstance(loaded, list):
            results = loaded
        elif isinstance(loaded, dict):
            results = [loaded]
    except Exception:
        pass

    # Attempt 2: Balanced brace scanner for concatenated/spaced JSON objects
    if not results:
        depth = 0
        start = -1
        in_string = False
        escape = False

        for i, char in enumerate(text):
            if char == '"' and not escape:
                in_string = not in_string
            elif char == '\\' and in_string:
                escape = not escape
                continue
            elif not in_string:
                if char == '{':
                    if depth == 0:
                        start = i
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0 and start != -1:
                        chunk = text[start : i + 1]
                        try:
                            obj = json.loads(chunk)
                            if isinstance(obj, dict):
                                results.append(obj)
                        except Exception:
                            # Try simple fix for trailing commas
                            try:
                                fixed = re.sub(r",\s*([}\]])", r"\1", chunk)
                                obj = json.loads(fixed)
                                if isinstance(obj, dict):
                                    results.append(obj)
                            except Exception:
                                pass
                        start = -1
            escape = False

    # Attempt 3: Line by line fallback
    if not results:
        for line in text.splitlines():
            line_str = line.strip().rstrip(",")
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    obj = json.loads(line_str)
                    if isinstance(obj, dict):
                        results.append(obj)
                except Exception:
                    pass

    normalized = []
    seen_mobiles = set()

    for item in results:
        if not isinstance(item, dict):
            continue

        # Extract mobile
        mobile_val = (
            item.get("mobile")
            or item.get("phone")
            or item.get("phoneNumber")
            or item.get("number")
            or item.get("phone_number")
            or ""
        )
        mobile_clean = re.sub(r"\D", "", str(mobile_val))
        if len(mobile_clean) == 12 and mobile_clean.startswith("91"):
            mobile = mobile_clean[2:]
        elif len(mobile_clean) > 10:
            mobile = mobile_clean[-10:]
        else:
            mobile = mobile_clean

        # Extract xo (mandatory)
        xo = (
            item.get("xo")
            or item.get("XO")
            or item.get("token")
            or item.get("session_token")
            or ""
        )

        # Extract optional ox
        ox = item.get("ox") or item.get("OX") or item.get("refresh_token") or ""

        # Extract or infer user_id
        user_id = item.get("user_id") or extract_user_id_from_xo(xo)

        # Both mobile and xo are mandatory
        if mobile and xo:
            # Prevent duplicate identical accounts in same paste
            dedup_key = f"{mobile}_{xo[:20]}"
            if dedup_key in seen_mobiles:
                continue
            seen_mobiles.add(dedup_key)

            # Build standardized complete Meesho session object
            identity = item.get("identity") or {}
            instance_id = str(
                item.get("instance_id")
                or identity.get("instance_id")
                or "7de6c1af957b1d6985e930b16deddb92"
            )
            gaid = str(
                item.get("gaid")
                or identity.get("gaid")
                or "3e46198c-bed4-4938-baa5-8f50e1b64765"
            )

            norm_item = {
                "mobile": mobile,
                "phone": f"+91{mobile}",
                "user_id": user_id,
                "xo": xo,
                "ox": ox,
                "instance_id": instance_id,
                "gaid": gaid,
                "authorization": item.get("authorization") or "32c4d8137cn9eb493a1921f203173080",
                "identity": {
                    "instance_id": instance_id,
                    "gaid": gaid,
                    "android_id": identity.get("android_id", "a43194698daf410c"),
                    "app_session_id": identity.get("app_session_id", "27384a7e-f99a-4602-b12e-9cf8c6cd01bb"),
                    "shield_session_id": identity.get("shield_session_id", "1a047084893d4f8fb23f1adebb000cf8"),
                    "make": identity.get("make", "Samsung"),
                    "model": identity.get("model", "Galaxy A54"),
                    "build": identity.get("build", "UP1A.231005.007"),
                    "android": identity.get("android", "14"),
                },
                # Default ratings & comments if not provided
                "rating": int(item.get("rating", 5)),
                "comments": str(item.get("comments", "Very good quality, fabric is soft and comfortable. Value for money!")),
            }

            # Check and tag token expiration
            is_exp, exp_ts = is_token_expired(xo)
            norm_item["token_exp"] = exp_ts
            norm_item["is_expired"] = is_exp

            normalized.append(norm_item)

    return normalized


def parse_multi_jsons_with_report(raw_text: str) -> Dict[str, Any]:
    """
    Parses accounts and returns detailed diagnostics including counts and expired token detection.
    """
    accounts = parse_multi_jsons(raw_text)
    expired_accounts = [a for a in accounts if a.get("is_expired")]
    return {
        "accounts": accounts,
        "valid_count": len(accounts),
        "expired_count": len(expired_accounts),
        "expired_accounts": expired_accounts,
    }


