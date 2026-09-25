from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from source_provenance import ROLE_POLICY

class SecureCaptureError(ValueError): pass
CONTENT_TYPES = {"SCOUT":("application/json",),"LEDGER":("application/json",),"PULSE":("application/json",),"SIGNAL":("application/rss+xml","application/xml","text/xml"),"FLUX":("application/json",),"SKEPTIC":("application/json",)}
MAX_BODY_BYTES = {"SCOUT":2_000_000,"LEDGER":2_000_000,"PULSE":1_000_000,"SIGNAL":3_000_000,"FLUX":1_000_000,"SKEPTIC":1_000_000}

@dataclass(frozen=True)
class TransportRecord:
    role:str; requested_url:str; final_url:str; method:str; status_code:int; content_type:str; fetched_at:datetime; tls_verified:bool; redirect_count:int; body_sha256:str; body_size:int
    def canonical_mapping(self)->dict:
        d=asdict(self); d["fetched_at"]=self.fetched_at.isoformat(); return d
    def sha256(self)->str:
        return hashlib.sha256(json.dumps(self.canonical_mapping(),sort_keys=True,separators=(",",":")).encode()).hexdigest()
    def validate(self, *, now:datetime, body:bytes, max_age_seconds:int=60)->None:
        if self.role not in ROLE_POLICY: raise SecureCaptureError("UNKNOWN_ROLE")
        if self.method!="GET": raise SecureCaptureError("NON_READONLY_METHOD")
        if self.status_code!=200: raise SecureCaptureError("BAD_HTTP_STATUS")
        if self.redirect_count!=0 or self.requested_url!=self.final_url: raise SecureCaptureError("REDIRECT_NOT_ALLOWED")
        if not self.tls_verified: raise SecureCaptureError("TLS_NOT_VERIFIED")
        if self.fetched_at.tzinfo is None or now.tzinfo is None: raise SecureCaptureError("INVALID_TIMESTAMP")
        age=now.astimezone(timezone.utc)-self.fetched_at.astimezone(timezone.utc)
        if age<timedelta(0) or age>timedelta(seconds=max_age_seconds): raise SecureCaptureError("STALE_OR_FUTURE_CAPTURE")
        _,host,path_prefix,_=ROLE_POLICY[self.role]
        p=urlparse(self.requested_url)
        if (p.scheme!="https" or p.hostname!=host or p.port not in (None,443) or p.username or p.password or p.fragment or not p.path.startswith(path_prefix)): raise SecureCaptureError("UNAPPROVED_ENDPOINT")
        if p.netloc not in (host,f"{host}:443"): raise SecureCaptureError("UNAPPROVED_NETLOC")
        ct=self.content_type.split(";",1)[0].strip().lower()
        if ct not in CONTENT_TYPES[self.role]: raise SecureCaptureError("UNAPPROVED_CONTENT_TYPE")
        if not isinstance(body,(bytes,bytearray)): raise SecureCaptureError("INVALID_BODY")
        if len(body)!=self.body_size: raise SecureCaptureError("BODY_SIZE_MISMATCH")
        if len(body)>MAX_BODY_BYTES[self.role]: raise SecureCaptureError("BODY_TOO_LARGE")
        if hashlib.sha256(bytes(body)).hexdigest()!=self.body_sha256 or len(self.body_sha256)!=64: raise SecureCaptureError("BODY_HASH_MISMATCH")

def make_transport_record(*, role:str,url:str,fetched_at:datetime,body:bytes,content_type:str,status_code:int=200,tls_verified:bool=True,redirect_count:int=0,final_url:str|None=None,method:str="GET")->TransportRecord:
    if final_url is None: final_url=url
    return TransportRecord(role,url,final_url,method,status_code,content_type,fetched_at,tls_verified,redirect_count,hashlib.sha256(body).hexdigest(),len(body))
