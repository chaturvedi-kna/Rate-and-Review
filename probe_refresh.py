import json, requests, base64

s = json.load(open('meesho_account_8869049741.json'))
user_id = s['user_id']
phone = s.get('phone') or f"+91{s.get('mobile', '')}"
identity = s.get('identity') or {}

headers = {
    'Authorization': '32c4d8137cn9eb493a1921f203173080',
    'App-Version': '29.5',
    'App-Version-Code': '868',
    'Instance-Id': s['instance_id'],
    'Country-Iso': 'in',
    'Application-Id': 'com.meesho.supply',
    'App-Session-Id': identity.get('app_session_id', ''),
    'App-Sdk-Version': '34',
    'App-Client-Id': 'android',
    'Shield-Session-Id': '1a047084893d4f8fb23f1adebb000cf8',
    'Xo': s['xo'],
    'App-User-Id': str(user_id),
    'U-Token': base64.b64encode(phone.encode()).decode(),
    'Meesho-User-Context': 'logged_in',
    'Accept': 'application/json',
    'Content-Type': 'application/json; charset=UTF-8',
    'User-Agent': 'okhttp/4.9.0'
}

base_url = 'https://prod.meeshoapi.com'

endpoints = [
    # Variations of token/session refresh
    ('POST', '/api/1.0/user/refresh'),
    ('POST', '/api/2.0/user/refresh'),
    ('POST', '/api/1.0/user/token/refresh'),
    ('POST', '/api/2.0/user/token/refresh'),
    ('POST', '/api/1.0/auth/refresh'),
    ('POST', '/api/2.0/auth/refresh'),
    ('POST', '/api/1.0/auth/token/refresh'),
    ('POST', '/api/2.0/auth/token/refresh'),
    ('POST', '/api/1.0/session/refresh'),
    ('POST', '/api/2.0/session/refresh'),
    ('POST', '/api/1.0/user/session/refresh'),
    ('POST', '/api/2.0/user/session/refresh'),
    ('POST', '/api/1.0/token/refresh'),
    ('POST', '/api/2.0/token/refresh'),
    ('GET', '/api/1.0/user/refresh'),
    ('GET', '/api/2.0/user/refresh'),
    ('GET', '/api/1.0/user/token/refresh'),
    ('GET', '/api/2.0/user/token/refresh'),
    ('POST', '/api/1.0/user/xo/refresh'),
    ('POST', '/api/2.0/user/xo/refresh'),
    ('POST', '/api/1.0/user/reauth'),
    ('POST', '/api/2.0/user/reauth'),
    ('POST', '/api/1.0/auth/reauth'),
    ('POST', '/api/2.0/auth/reauth'),
]

payloads = [
    {'ox': s.get('ox'), 'user_id': user_id},
    {'refresh_token': s.get('ox'), 'user_id': user_id},
    {'token': s.get('ox'), 'user_id': user_id},
]

for method, path in endpoints:
    url = f"{base_url}{path}"
    # try with first payload
    pl = payloads[0] if method == 'POST' else None
    try:
        r = requests.request(method, url, headers=headers, json=pl, timeout=5)
        if r.status_code != 404:
            print(f"FOUND! {method} {path} -> {r.status_code} {r.text[:200]}")
    except Exception as e:
        pass
print("Done probing endpoints.")

