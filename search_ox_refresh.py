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
        req = decode(elem.find("request"))
        resp = decode(elem.find("response"))
        
        # Check for ox as key
        if '"ox"' in req or '"ox":' in req:
            print("REQ with ox:", url)
        if '"ox"' in resp or '"ox":' in resp:
            print("RESP with ox:", url)
            
        # Check for refresh in url or body
        if "refresh" in url.lower() or "token" in url.lower():
            if "google" not in url and "appsflyer" not in url and "otpless" not in url:
                print("Endpoint with refresh/token:", url)
        elem.clear()

