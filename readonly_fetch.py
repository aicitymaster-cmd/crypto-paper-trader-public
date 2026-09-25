"""Strict read-only HTTPS fetcher for approved PUBLIC endpoints only."""
from __future__ import annotations
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Final
from urllib.parse import urlparse
from secure_capture import make_transport_record, TransportRecord, MAX_BODY_BYTES
from source_provenance import ROLE_POLICY

class ReadOnlyFetchError(RuntimeError):
    pass

USER_AGENT: Final = "crypto-paper-trader-readonly-final-candidate/1.0"
TIMEOUT_SECONDS: Final = 8
BASE_URLS: Final = {
    "SCOUT": "https://api.bitbank.cc/v1/spot/status",
    "LEDGER": "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics",
    "PULSE": "https://coincheck.com/api/ticker",
    "SIGNAL": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "FLUX": "https://api.bitflyer.com/v1/ticker",
    "SKEPTIC": "https://api.alternative.me/fng/",
}

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReadOnlyFetchError("REDIRECT_NOT_ALLOWED")

def build_url(role: str, *, symbol: str) -> str:
    symbol = str(symbol).upper()
    if role == "SCOUT": return BASE_URLS[role]
    if role == "LEDGER":
        asset = {"BTC":"btc","ETH":"eth","SOL":"sol","XRP":"xrp","DOGE":"doge"}.get(symbol)
        if asset is None: raise ReadOnlyFetchError("UNSUPPORTED_SYMBOL")
        return f"{BASE_URLS[role]}?assets={asset}&metrics=AdrActCnt&page_size=2&paging_from=end"
    if role == "PULSE":
        pair = {"BTC":"btc_jpy","ETH":"eth_jpy","SOL":"sol_jpy","XRP":"xrp_jpy","DOGE":"doge_jpy"}.get(symbol)
        if pair is None: raise ReadOnlyFetchError("UNSUPPORTED_SYMBOL")
        return f"{BASE_URLS[role]}?pair={pair}"
    if role == "SIGNAL": return BASE_URLS[role]
    if role == "FLUX":
        pair = {"BTC":"BTC_JPY","ETH":"ETH_JPY","XRP":"XRP_JPY"}.get(symbol)
        if pair is None: raise ReadOnlyFetchError("UNSUPPORTED_SYMBOL")
        return f"{BASE_URLS[role]}?product_code={pair}"
    if role == "SKEPTIC": return f"{BASE_URLS[role]}?limit=2&format=json"
    raise ReadOnlyFetchError("UNKNOWN_ROLE")

def _assert_endpoint(role: str, url: str) -> None:
    if role not in ROLE_POLICY or role not in BASE_URLS: raise ReadOnlyFetchError("UNKNOWN_ROLE")
    p = urlparse(url)
    expected_host = urlparse(BASE_URLS[role]).hostname
    expected_path = urlparse(BASE_URLS[role]).path
    if p.scheme != "https" or p.hostname != expected_host or p.port not in (None,443): raise ReadOnlyFetchError("UNAPPROVED_ENDPOINT")
    if p.username or p.password or p.fragment: raise ReadOnlyFetchError("UNAPPROVED_ENDPOINT")
    if p.path != expected_path: raise ReadOnlyFetchError("UNAPPROVED_ENDPOINT")

def fetch_public(role: str, *, symbol: str, now: datetime | None = None) -> tuple[bytes, TransportRecord]:
    if now is None: now = datetime.now(timezone.utc)
    if now.tzinfo is None: raise ReadOnlyFetchError("NAIVE_NOW")
    url = build_url(role, symbol=symbol)
    _assert_endpoint(role, url)
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(), urllib.request.HTTPSHandler(context=context))
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    max_bytes = MAX_BODY_BYTES[role]
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            status = int(getattr(resp, "status", 0))
            final_url = resp.geturl()
            content_type = resp.headers.get_content_type()
            body = resp.read(max_bytes + 1)
    except ReadOnlyFetchError: raise
    except urllib.error.HTTPError as exc: raise ReadOnlyFetchError(f"HTTP_{exc.code}") from exc
    except Exception as exc: raise ReadOnlyFetchError("NETWORK_READ_FAILED") from exc
    if len(body) > max_bytes: raise ReadOnlyFetchError("BODY_TOO_LARGE")
    if final_url != url: raise ReadOnlyFetchError("REDIRECT_NOT_ALLOWED")
    record = make_transport_record(role=role, url=url, fetched_at=now, body=body, content_type=content_type, status_code=status, tls_verified=True, redirect_count=0, final_url=final_url, method="GET")
    record.validate(now=now, body=body)
    return body, record
