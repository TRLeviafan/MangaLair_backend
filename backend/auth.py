from __future__ import annotations
import hashlib
import hmac
import os
import time
from typing import Dict, Optional
from urllib.parse import parse_qsl

INITDATA_TTL = int(os.getenv("INITDATA_TTL", "86400"))
DEBUG_INITDATA = os.getenv("DEBUG_INITDATA", "0") == "1"

class InitDataError(Exception):
    pass

def _secret_webappdata(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()

def _secret_legacy(bot_token: str) -> bytes:
    return hashlib.sha256(bot_token.encode("utf-8")).digest()

def _build_data_check_string(pairs: Dict[str, str]) -> str:
    # Exclude ONLY 'hash' (include 'signature' if present)
    items = [(k, v) for k, v in pairs.items() if k != "hash"]
    items.sort(key=lambda kv: kv[0])
    return "\n".join([f"{k}={v}" for k, v in items])

def _hex_hmac_sha256(msg: str, key: bytes) -> str:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()

def parse_and_verify_init_data(raw: str, bot_token: str) -> Dict[str, str]:
    if not raw:
        raise InitDataError("empty initData")
    pairs_list = parse_qsl(raw, keep_blank_values=True, strict_parsing=False)
    pairs: Dict[str, str] = {k: v for k, v in pairs_list}

    hash_value = pairs.get("hash")
    if not hash_value:
        raise InitDataError("hash missing")

    auth_date = pairs.get("auth_date")
    if not auth_date or not auth_date.isdigit():
        raise InitDataError("auth_date invalid")

    now = int(time.time())
    if INITDATA_TTL > 0 and now - int(auth_date) > INITDATA_TTL:
        raise InitDataError("initData expired")

    dcs = _build_data_check_string(pairs)

    secret1 = _secret_webappdata(bot_token)
    calc1 = _hex_hmac_sha256(dcs, secret1)
    if calc1 == hash_value:
        if DEBUG_INITDATA:
            print("[initData] OK via WebAppData. DCS=", dcs)
        return pairs

    secret2 = _secret_legacy(bot_token)
    calc2 = _hex_hmac_sha256(dcs, secret2)
    if calc2 == hash_value:
        if DEBUG_INITDATA:
            print("[initData] OK via legacy SHA256(bot_token). DCS=", dcs)
        return pairs

    if DEBUG_INITDATA:
        print("[initData] FAIL. DCS=", dcs)
        print("[initData] Provided hash=", hash_value)
        print("[initData] Calc WebAppData=", calc1)
        print("[initData] Calc Legacy    =", calc2)
    raise InitDataError("hash mismatch")

def extract_init_data_from_request(request) -> Optional[str]:
    raw = request.headers.get("X-Telegram-Init-Data")
    if not raw:
        raw = request.query_params.get("initData")
    return raw
