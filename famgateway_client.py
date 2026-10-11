import hmac
import hashlib
import json
import os
import requests
from typing import Tuple, Dict, Any, Optional

FAMGATEWAY_BASE_URL = "https://famgateway.in/api"


def get_api_key(override_key: str = None) -> str:
    return (override_key or os.environ.get("FAMGATEWAY_API_KEY") or "").strip()


def create_order(
    amount: float,
    customer_name: str,
    redirect_url: str,
    webhook_url: str,
    api_key: str = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Creates a payment session with FamGateway API.
    Returns (success, response_dict).
    """
    key = get_api_key(api_key)
    if not key:
        return False, {"error": "FamGateway API key is not configured."}

    payload = {
        "amount": round(float(amount), 2),
        "customer_name": customer_name,
        "redirect_url": redirect_url,
        "webhook_url": webhook_url,
    }

    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": key,
    }

    try:
        resp = requests.post(
            f"{FAMGATEWAY_BASE_URL}/create-order",
            json=payload,
            headers=headers,
            timeout=10,
        )
        data = resp.json()
        if resp.status_code in (200, 201) and (data.get("checkout_url") or data.get("status") == "success"):
            return True, data
        return False, data
    except Exception as exc:
        return False, {"error": f"FamGateway connection error: {exc}"}


def verify_order(order_id: str, api_key: str = None) -> Tuple[bool, Dict[str, Any]]:
    """
    Direct server-to-server verification of a FamGateway order.
    """
    key = get_api_key(api_key)
    if not key or not order_id:
        return False, {"error": "API Key or Order ID missing"}

    try:
        resp = requests.get(
            f"{FAMGATEWAY_BASE_URL}/verify-order.php",
            params={"api_key": key, "order_id": order_id},
            timeout=10,
        )
        data = resp.json()
        status = str(data.get("status", "")).upper()
        if status in ("SUCCESS", "PAID", "COMPLETED"):
            return True, data
        return False, data
    except Exception as exc:
        return False, {"error": str(exc)}


def verify_webhook_signature(raw_body: bytes, signature_header: str, api_key: str = None) -> bool:
    """
    Validates HMAC-SHA256 signature sent in X-FamGateway-Signature header.
    """
    key = get_api_key(api_key)
    if not key or not signature_header:
        return False

    computed = hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed.lower(), signature_header.lower())

