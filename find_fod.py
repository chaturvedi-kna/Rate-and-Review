import xml.etree.ElementTree as ET
import base64

def decode(el):
    if el is None or el.text is None: return ""
    raw = el.text.encode("utf-8")
    if el.get("base64") == "true":
        return base64.b64decode(raw).decode("latin-1", errors="replace")
    return el.text

for event, elem in ET.iterparse("review meesho.xml", events=("end",)):
    if elem.tag == "item":
        url = elem.findtext("url", "")
        if "fod-personalisation" in url or "configs/user" in url:
            print("="*60)
            print("URL:", url)
            print("REQ:")
            print(decode(elem.find("request"))[:500])
            print("RESP:")
            print(decode(elem.find("response"))[:500])
        elem.clear()

