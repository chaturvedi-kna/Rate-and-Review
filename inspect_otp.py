import xml.etree.ElementTree as ET
import base64

def decode(el):
    if el is None or el.text is None: return ""
    raw = el.text.encode("utf-8")
    if el.get("base64") == "true":
        return base64.b64decode(raw).decode("utf-8", errors="replace")
    return el.text

for event, elem in ET.iterparse("review meesho.xml", events=("end",)):
    if elem.tag == "item":
        url = elem.findtext("url", "")
        if "otpless.app" in url and "otp" in url:
            print("="*60)
            print("URL:", url)
            req = decode(elem.find("request"))
            resp = decode(elem.find("response"))
            print("REQ BODY:\n", req.split('\r\n\r\n')[1] if '\r\n\r\n' in req else '')
            print("RESP BODY:\n", resp.split('\r\n\r\n')[1] if '\r\n\r\n' in resp else '')
        elem.clear()

