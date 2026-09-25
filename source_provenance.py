from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

class ProvenanceError(ValueError): pass

ROLE_POLICY = {
    "SCOUT": ("bitbank", "api.bitbank.cc", "/v1/spot/", "bitbank-status-pairs-v1"),
    "LEDGER": ("coinmetrics", "community-api.coinmetrics.io", "/v4/timeseries/asset-metrics", "coinmetrics-adractcnt-v1"),
    "PULSE": ("coincheck", "coincheck.com", "/api/ticker", "coincheck-ticker-v1"),
    "SIGNAL": ("coindesk", "www.coindesk.com", "/", "coindesk-rss-v1"),
    "FLUX": ("bitflyer", "api.bitflyer.com", "/v1/ticker", "bitflyer-ticker-v1"),
    "SKEPTIC": ("alternative-me", "api.alternative.me", "/fng/", "alternative-fng-v1"),
}

@dataclass(frozen=True)
class SourceReceipt:
    role: str; provider: str; url: str; fetched_at: datetime; payload_sha256: str; parser_id: str; evidence_sha256: str
    method: str = "GET"; authenticated_transport: bool = False; transport_record_sha256: str = ""
    def validate(self, *, now: datetime, payload: bytes, max_age_seconds: int = 60) -> None:
        if self.role not in ROLE_POLICY: raise ProvenanceError("UNKNOWN_ROLE")
        expected_provider, expected_host, path_prefix, expected_parser = ROLE_POLICY[self.role]
        if self.provider != expected_provider: raise ProvenanceError("UNAPPROVED_PROVIDER")
        p = urlparse(self.url)
        if (p.scheme != "https" or p.hostname != expected_host or p.username or p.password or p.fragment or not p.path.startswith(path_prefix)): raise ProvenanceError("UNAPPROVED_ENDPOINT")
        if self.method != "GET": raise ProvenanceError("NON_READONLY_METHOD")
        if self.parser_id != expected_parser: raise ProvenanceError("UNAPPROVED_PARSER")
        if self.fetched_at.tzinfo is None or now.tzinfo is None: raise ProvenanceError("INVALID_TIMESTAMP")
        age = now.astimezone(timezone.utc) - self.fetched_at.astimezone(timezone.utc)
        if age < timedelta(0) or age > timedelta(seconds=max_age_seconds): raise ProvenanceError("STALE_OR_FUTURE_RECEIPT")
        if hashlib.sha256(payload).hexdigest() != self.payload_sha256: raise ProvenanceError("PAYLOAD_HASH_MISMATCH")
        if len(self.payload_sha256) != 64: raise ProvenanceError("INVALID_PAYLOAD_HASH")
        if len(self.evidence_sha256) != 64: raise ProvenanceError("INVALID_EVIDENCE_HASH")
        if self.authenticated_transport and len(self.transport_record_sha256) != 64: raise ProvenanceError("INVALID_TRANSPORT_HASH")
    def validate_evidence_binding(self, evidence_mapping: dict) -> None:
        canonical = json.dumps(evidence_mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != self.evidence_sha256: raise ProvenanceError("EVIDENCE_HASH_MISMATCH")

def make_structural_receipt(*, role: str, provider: str, url: str, fetched_at: datetime, payload: bytes, parser_id: str, evidence_mapping: dict | None = None) -> SourceReceipt:
    if evidence_mapping is None: evidence_mapping = {}
    canonical = json.dumps(evidence_mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return SourceReceipt(role=role, provider=provider, url=url, fetched_at=fetched_at, payload_sha256=hashlib.sha256(payload).hexdigest(), parser_id=parser_id, evidence_sha256=hashlib.sha256(canonical).hexdigest())
