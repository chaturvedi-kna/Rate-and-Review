import json
import time
import uuid
import requests

OTPLESS_APP_ID = "XN07RN1IQC548C9YK5I4"
OTPLESS_LOGIN_URI = "otpless.xn07rn1iqc548c9yk5i4://otpless"
PACKAGE_NAME = "com.meesho.supply"
MEESHO_LOGIN_URL = "https://prod.meeshoapi.com/api/2.0/user/login"
DEFAULT_AUTHORIZATION = "32c4d8137cn9eb493a1921f203173080"


def send_otp(mobile: str) -> dict:
    """Trigger WhatsApp / SMS OTP to mobile via Otpless API."""
    headers = {
        "User-Agent": "okhttp/4.9.0",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }

    clean_mobile = mobile.lstrip("+").lstrip()
    if clean_mobile.startswith("91") and len(clean_mobile) == 12:
        full_mobile = clean_mobile
    elif len(clean_mobile) == 10:
        full_mobile = f"91{clean_mobile}"
    else:
        full_mobile = f"91{clean_mobile}"

    ts = int(time.time() * 1000)
    ts_id = f"{uuid.uuid4()}-{ts}"
    in_id = f"{uuid.uuid4()}-{ts}"

    params = {
        "origin": "https://otpless.com",
        "version": "V3",
        "tsId": ts_id,
        "inId": in_id,
        "isHeadless": "true",
        "platform": "android",
        "packageName": PACKAGE_NAME,
        "package": PACKAGE_NAME,
        "appId": OTPLESS_APP_ID,
        "loginUri": OTPLESS_LOGIN_URI,
    }

    # Step 1: Initialize state
    r_state = requests.get(
        "https://user-auth.otpless.app/v2/state",
        headers=headers,
        params=params,
        timeout=15,
    )
    r_state.raise_for_status()
    state = r_state.json().get("state")
    if not state:
        raise RuntimeError(f"Failed to get Otpless state: {r_state.text}")

    device_info = json.dumps({
        "platform": "android",
        "vendor": "Samsung",
        "browser": "",
        "connection": "",
        "language": "en-US",
        "cookieEnabled": "",
        "screenWidth": 1080,
        "screenHeight": 2340,
        "userAgent": "Dalvik/2.1.0 (Linux; U; Android 14; Galaxy A54 Build/UP1A.231005.007) otplesssdk",
        "timezoneOffset": 330,
        "cpuArchitecture": "arm64-v8a",
    })

    # Step 2: Trigger Intent (send OTP)
    payload = {
        "selectedCountryCode": "91",
        "mobile": full_mobile,
        "silentAuthEnabled": False,
        "hasWhatsapp": "false",
        "origin": "https://otpless.com",
        "version": "V4",
        "tsId": ts_id,
        "inId": in_id,
        "deviceInfo": device_info,
        "loginUri": OTPLESS_LOGIN_URI,
        "appId": OTPLESS_APP_ID,
        "isHeadless": True,
        "packageName": PACKAGE_NAME,
        "package": PACKAGE_NAME,
        "otpHash": "oBcOM6bXKNc",
        "platform": "HEADLESS",
        "isAutoIntent": True,
        "asId": "",
    }

    r_intent = requests.post(
        f"https://user-auth.otpless.app/v3/lp/user/transaction/intent/{state}",
        headers=headers,
        json=payload,
        timeout=15,
    )
    r_intent.raise_for_status()
    data = r_intent.json()
    ql = data.get("quantumLeap") or {}

    uid = ql.get("uid", "")
    channel_token = ql.get("channelAuthToken", "")
    as_id = ql.get("asId", "")
    comm_mode = ql.get("communicationMode", "SMS")

    print(f"[+] OTP sent via {comm_mode} to +{full_mobile}")

    return {
        "state": state,
        "full_mobile": full_mobile,
        "ts_id": ts_id,
        "in_id": in_id,
        "uid": uid,
        "channel_token": channel_token,
        "as_id": as_id,
        "device_info": device_info,
    }


def verify_otp_and_login(ctx: dict, otp: str, session: dict = None) -> tuple[dict, dict]:
    """Verify OTP with Otpless and perform login on Meesho to get fresh xo/ox."""
    headers = {
        "User-Agent": "okhttp/4.9.0",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }

    otp_clean = str(otp).strip()
    state = ctx["state"]
    full_mobile = ctx["full_mobile"]

    otp_payload = {
        "selectedCountryCode": "91",
        "mobile": full_mobile,
        "otp": otp_clean,
        "value": full_mobile,
        "isOTPAutoRead": "false",
        "uid": ctx["uid"],
        "token": ctx["channel_token"],
        "asId": ctx["as_id"],
        "origin": "https://otpless.com",
        "version": "V4",
        "tsId": ctx["ts_id"],
        "inId": ctx["in_id"],
        "deviceInfo": ctx["device_info"],
        "loginUri": OTPLESS_LOGIN_URI,
        "appId": OTPLESS_APP_ID,
        "isHeadless": True,
        "packageName": PACKAGE_NAME,
        "package": PACKAGE_NAME,
        "otpHash": "oBcOM6bXKNc",
        "platform": "HEADLESS",
    }

    print("Verifying OTP with Otpless...")
    r_verify = requests.post(
        f"https://user-auth.otpless.app/v3/lp/user/transaction/otp/{state}",
        headers=headers,
        json=otp_payload,
        timeout=15,
    )
    r_verify.raise_for_status()
    resp_data = r_verify.json()

    one_tap = resp_data.get("oneTap") or {}
    token = one_tap.get("token")
    id_token = one_tap.get("idToken")

    if not token or not id_token:
        # Check if authDetail has error or pending
        status = resp_data.get("authDetail", {}).get("status")
        raise RuntimeError(f"OTP verification failed. Status: {status}, Response: {resp_data}")

    print("[+] OTP verified successfully with Otpless!")

    # Step 3: Perform Meesho login
    sess = session or {}
    identity = sess.get("identity") or {}
    gaid = str(sess.get("gaid") or identity.get("gaid") or uuid.uuid4())
    instance_id = str(sess.get("instance_id") or identity.get("instance_id") or uuid.uuid4().hex)
    app_session_id = str(identity.get("app_session_id") or uuid.uuid4())

    meesho_headers = {
        "Authorization": str(sess.get("authorization") or DEFAULT_AUTHORIZATION),
        "App-Version": "29.5",
        "App-Version-Code": "868",
        "Instance-Id": instance_id,
        "Country-Iso": "in",
        "Application-Id": PACKAGE_NAME,
        "App-Session-Id": app_session_id,
        "App-Sdk-Version": "34",
        "App-Client-Id": "android",
        "Shield-Session-Id": "1a047084893d4f8fb23f1adebb000cf8",
        "Xo": str(identity.get("anon_xo") or sess.get("xo") or ""),
        "Meesho-User-Context": "anonymous",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "okhttp/4.9.0",
    }

    meesho_payload = {
        "login_type": "otpless",
        "otpless": {
            "token": token,
            "id_token": id_token,
            "aes_key_encrypted": "",
            "version": "v2",
        },
        "ga_id": gaid,
    }

    print("Logging into Meesho with new Otpless tokens...")
    r_login = requests.post(
        MEESHO_LOGIN_URL,
        headers=meesho_headers,
        json=meesho_payload,
        timeout=15,
    )
    r_login.raise_for_status()
    login_resp = r_login.json()

    user_info = login_resp.get("user") or {}
    xoox = login_resp.get("xoox") or {}

    print(f"[+] Meesho login successful! user_id: {user_info.get('user_id')}")
    return user_info, xoox

