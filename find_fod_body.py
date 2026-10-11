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
        if "fod-personalisation" in url:
            print("="*60)
            req = decode(elem.find("request"))
            resp = decode(elem.find("response"))
            req_body = req.split('\r\n\r\n')[1] if '\r\n\r\n' in req else ''
            resp_body = resp.split('\r\n\r\n')[1] if '\r\n\r\n' in resp else ''
            print("REQ BODY:\n", req_body[:500].encode('ascii', errors='replace').decode())
            print("RESP BODY:\n", resp_body[:500].encode('ascii', errors='replace').decode())
        elem.clear()

