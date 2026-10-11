"""
Indian Proxy Manager with ProxyScrape Free API Integration & Smart Auto-Failover.
Fetches Indian proxies from ProxyScrape free APIs and automatically rotates / fails over
to another Indian proxy if the current one drops, times out, or fails.
"""

import os
import time
import threading
import logging
from typing import Optional, Dict, List, Any
import requests

logger = logging.getLogger("ProxyManager")

PROXY_FETCH_URLS = [
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&country=IN&proxy_format=protocolipport&format=text",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http,https&timeout=10000&country=IN&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=20000&country=IN",
]

CACHE_TTL_SECONDS = 900          # 15 minutes cache for proxy list
FAILURE_COOLDOWN_SECONDS = 600   # 10 minutes cooldown before retrying a failed proxy


class IndianProxyPool:
    """Thread-safe Indian proxy pool fetched from ProxyScrape with rotation and failover."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proxies: List[str] = []
        self._failed_proxies: Dict[str, float] = {}  # proxy_url -> failure_timestamp
        self._active_proxy: Optional[str] = None
        self._last_fetch_time: float = 0.0
        self._current_index: int = 0

    def fetch_proxyscrape_indian_proxies(self, force: bool = False) -> List[str]:
        """Fetches fresh Indian proxy list from ProxyScrape free endpoints."""
        now = time.time()
        with self._lock:
            if not force and self._proxies and (now - self._last_fetch_time < CACHE_TTL_SECONDS):
                return list(self._proxies)

        collected = []
        for url in PROXY_FETCH_URLS:
            try:
                resp = requests.get(url, timeout=6)
                if resp.status_code == 200 and resp.text:
                    for line in resp.text.splitlines():
                        p = line.strip()
                        if not p or p.startswith("#") or "<" in p:
                            continue
                        if not (p.startswith("http://") or p.startswith("https://") or p.startswith("socks4://") or p.startswith("socks5://")):
                            p = f"http://{p}"
                        if p not in collected:
                            collected.append(p)
            except Exception as e:
                logger.debug(f"Failed fetching proxies from {url}: {e}")

        with self._lock:
            if collected:
                self._proxies = collected
                self._last_fetch_time = now
                self._current_index = 0
                logger.info(f"[ProxyManager] Loaded {len(self._proxies)} Indian proxies from ProxyScrape.")
            return list(self._proxies)

    def get_candidate_proxies(self) -> List[str]:
        """Returns candidate proxies excluding those currently in failure cooldown."""
        now = time.time()
        with self._lock:
            # Clean expired failures
            self._failed_proxies = {
                p: ts for p, ts in self._failed_proxies.items()
                if (now - ts) < FAILURE_COOLDOWN_SECONDS
            }

            candidates = [p for p in self._proxies if p not in self._failed_proxies]
            if not candidates and self._proxies:
                # If all proxies failed, reset the failure tracker to try them again
                self._failed_proxies.clear()
                candidates = list(self._proxies)
            return candidates

    def get_next_proxy(self, failed_proxy: Optional[str] = None, reason: str = "") -> Optional[str]:
        """Marks current/failed proxy as failed and selects the next available Indian proxy."""
        with self._lock:
            now = time.time()
            if failed_proxy:
                self._failed_proxies[failed_proxy] = now
                logger.warning(f"[ProxyManager] Proxy '{failed_proxy}' marked failed ({reason}).")

        if not self._proxies:
            self.fetch_proxyscrape_indian_proxies()

        candidates = self.get_candidate_proxies()
        with self._lock:
            if not candidates:
                self._active_proxy = None
                return None

            self._current_index = (self._current_index + 1) % len(candidates)
            self._active_proxy = candidates[self._current_index]
            logger.info(f"[ProxyManager] Switched to Indian proxy: {self._active_proxy} (Available: {len(candidates)})")
            return self._active_proxy

    def get_current_or_next(self) -> Optional[str]:
        """Gets currently active proxy or next available one."""
        with self._lock:
            if self._active_proxy and self._active_proxy not in self._failed_proxies:
                return self._active_proxy

        return self.get_next_proxy()

    def mark_success(self, proxy: str):
        """Marks proxy as confirmed working and keeps it active."""
        with self._lock:
            self._active_proxy = proxy
            self._failed_proxies.pop(proxy, None)


# Global singleton instance
_POOL = IndianProxyPool()


def get_configured_proxy() -> Optional[str]:
    """Retrieves custom proxy configured via DB setting or INDIAN_PROXY env var."""
    proxy_str = os.environ.get("INDIAN_PROXY", "").strip()
    if not proxy_str:
        try:
            import db
            proxy_str = (db.get_setting("meesho_proxy") or "").strip()
        except Exception:
            pass

    if proxy_str and proxy_str.lower() not in ("auto", "proxyscrape", "none", "false", ""):
        if not (proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks5://")):
            proxy_str = f"http://{proxy_str}"
        return proxy_str
    return None


def get_meesho_proxies(custom_proxy: str = None) -> Optional[Dict[str, str]]:
    """Returns requests-compatible dictionary {'http': ..., 'https': ...}."""
    p = custom_proxy or get_configured_proxy()
    if p:
        return {"http": p, "https": p}

    # Fetch from ProxyScrape pool
    auto_p = _POOL.get_current_or_next()
    if auto_p:
        return {"http": auto_p, "https": auto_p}
    return None


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    max_proxy_retries: int = 5,
    timeout: int = 15,
    log_callback = None,
    **kwargs
) -> requests.Response:
    """
    Executes request using Indian proxy from ProxyScrape with automatic failover!
    If proxy connection drops, times out, or fails, automatically switches to another
    Indian proxy from ProxyScrape and retries until success or retries exhausted.
    """
    def log(msg: str):
        if log_callback:
            log_callback(msg)
        print(msg)

    custom_p = get_configured_proxy()
    last_exc = None

    for attempt in range(1, max_proxy_retries + 1):
        if custom_p and attempt == 1:
            current_proxy = custom_p
        else:
            current_proxy = _POOL.get_current_or_next()

        if current_proxy:
            session.proxies = {"http": current_proxy, "https": current_proxy}
        else:
            session.proxies = {}

        try:
            resp = session.request(
                method=method,
                url=url,
                timeout=timeout,
                **kwargs
            )

            # Check for proxy gateway errors (407, 502, 503, 504)
            if resp.status_code in (407, 502, 503, 504) and current_proxy:
                log(f"  [Proxy Failover] Proxy {current_proxy} returned HTTP {resp.status_code}. Choosing another Indian proxy...")
                _POOL.get_next_proxy(failed_proxy=current_proxy, reason=f"HTTP {resp.status_code}")
                continue

            # Connection reached target server (200, 400, 401, etc.)
            if current_proxy:
                _POOL.mark_success(current_proxy)

            return resp

        except (
            requests.exceptions.ProxyError,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ReadTimeout,
            requests.exceptions.SSLError,
            requests.exceptions.ChunkedEncodingError,
        ) as exc:
            last_exc = exc
            exc_name = exc.__class__.__name__
            if current_proxy:
                log(f"  [Proxy Failover] Proxy {current_proxy} failed ({exc_name}). Choosing another Indian proxy from ProxyScrape (attempt {attempt}/{max_proxy_retries})...")
                _POOL.get_next_proxy(failed_proxy=current_proxy, reason=exc_name)
            else:
                log(f"  [Proxy Failover] Direct connection failed ({exc_name}). Attempting next Indian proxy...")
                _POOL.get_next_proxy()

        except Exception as exc:
            last_exc = exc
            log(f"  [Proxy Failover] Unexpected error on proxy {current_proxy}: {exc}. Retrying with another proxy...")
            if current_proxy:
                _POOL.get_next_proxy(failed_proxy=current_proxy, reason=str(exc))

    # If all proxy attempts fail, try direct connection as fallback
    log(f"  [Proxy Notice] All {max_proxy_retries} Indian proxy attempts failed/timed out. Attempting direct connection as fallback...")
    session.proxies = {}
    try:
        return session.request(method=method, url=url, timeout=timeout, **kwargs)
    except Exception as direct_exc:
        if last_exc:
            raise last_exc
        raise direct_exc
