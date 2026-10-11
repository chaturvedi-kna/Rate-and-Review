import os
import time
import requests
from typing import Optional, Dict

_CACHED_PROXIES = []
_LAST_FETCH_TIME = 0


def get_meesho_proxies(custom_proxy: str = None) -> Optional[Dict[str, str]]:
    """
    Returns proxy dictionary for requests (e.g. {'http': ..., 'https': ...}).
    Checks custom_proxy first, then INDIAN_PROXY env var, then optional auto Indian proxy.
    """
    global _CACHED_PROXIES, _LAST_FETCH_TIME

    proxy_str = (custom_proxy or os.environ.get("INDIAN_PROXY") or "").strip()

    if proxy_str and proxy_str.lower() != "auto":
        if not proxy_str.startswith("http://") and not proxy_str.startswith("https://") and not proxy_str.startswith("socks5://"):
            proxy_str = f"http://{proxy_str}"
        return {"http": proxy_str, "https": proxy_str}

    if proxy_str.lower() == "auto":
        # Fetch free Indian proxies if cache expired (15 mins)
        now = time.time()
        if not _CACHED_PROXIES or now - _LAST_FETCH_TIME > 900:
            try:
                url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=IN&ssl=all&anonymity=all"
                resp = requests.get(url, timeout=4)
                if resp.status_code == 200:
                    _CACHED_PROXIES = [p.strip() for p in resp.text.splitlines() if p.strip()]
                    _LAST_FETCH_TIME = now
            except Exception:
                pass

        if _CACHED_PROXIES:
            selected = _CACHED_PROXIES[0]
            p_formatted = f"http://{selected}"
            return {"http": p_formatted, "https": p_formatted}

    return None

