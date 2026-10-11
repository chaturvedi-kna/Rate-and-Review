
import base64
import json
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

SENSITIVE = {
    "authorization", "xo", "cookie", "set-cookie",
    "app-session-id", "instance-id", "app-gaid",
    "app-fcm-token", "shield-session-id",
    "x-goog-api-key", "refreshtoken", "token",
}

TARGETS = (
    "/api/1.0/anonymous/config",
    "/api/1.0/anonymous/fod-personalisation",
    "/api/1.0/configs/user",
    "/api/2.0/configs/user",
    "/v1/projects/meesho-supply/installations",
)


def decode_item(item, name):
    element = item.find(name)
    if element is None or element.text is None:
        return b""
    raw = element.text.encode("utf-8")
    if element.get("base64") == "true":
        try:
            return base64.b64decode(raw)
        except Exception:
            pass
    return raw


def parse_http(raw):
    text = raw.decode("latin-1", errors="replace")
    head, sep, body = text.partition("\r\n\r\n")
    if not sep:
        head, _, body = text.partition("\n\n")

    lines = head.replace("\r", "").split("\n")
    headers = {}

    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    return lines[0] if lines else "", headers, body


def redact(name, value):
    if name.lower() in SENSITIVE:
        return "<REDACTED>"
    return value


def find_xo_fields(obj, path="$"):
    found = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}"
            if key.lower() == "xo":
                found.append(child)
            found.extend(find_xo_fields(value, child))

    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found.extend(find_xo_fields(value, f"{path}[{i}]"))

    return found


def main(filename):
    root = ET.parse(filename).getroot()
    items = root.findall("item")
    print(f"Loaded {len(items)} Burp entries from {filename}")

    for number, item in enumerate(items, 1):
        url = item.findtext("url", "")
        path = urlparse(url).path

        if not any(target in path for target in TARGETS):
            continue

        request = decode_item(item, "request")
        response = decode_item(item, "response")

        req_line, headers, body = parse_http(request)
        resp_line, resp_headers, resp_body = parse_http(response)

        print("\n" + "=" * 72)
        print(f"ENTRY {number}: {req_line}")
        print(f"URL: {url}")
        print(f"Response: {resp_line}")

        print("\nRequest headers:")
        for key, value in headers.items():
            print(f"  {key}: {redact(key, value)}")

        if body.strip():
            print("\nRequest body:")
            try:
                print(json.dumps(json.loads(body), indent=2))
            except Exception:
                print(f"<non-JSON body, {len(body)} characters>")

        if "config" in path or "installations" in path:
            try:
                data = json.loads(resp_body)
                fields = find_xo_fields(data)
                print("\nResponse JSON field paths named 'xo':")
                print("\n".join(fields) if fields else "None found")
            except Exception:
                print("\nResponse body is not directly parseable JSON.")

        print("\nResponse headers:")
        for key, value in resp_headers.items():
            print(f"  {key}: {redact(key, value)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Usage: python inspect_burp.py "C:\\path\\to\\burp(1)"')
        sys.exit(1)

    main(sys.argv[1])
