"""NIP-98 HTTP authentication for HOSAKA requests.

One kind 27235 event per request, signed with the CLI identity, bound to the
exact URL and method. A nonce tag keeps two requests in the same second from
being the same event: the server refuses replays.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any, Dict, Optional

from coincurve import PrivateKey


def nip98_event(
    privkey_hex: str,
    pubkey_hex: str,
    url: str,
    method: str,
    *,
    created_at: Optional[int] = None,
) -> Dict[str, Any]:
    """Build and sign the kind 27235 event for one request."""
    sk = PrivateKey(bytes.fromhex(privkey_hex))
    derived = sk.public_key.format(compressed=True)[1:].hex()
    if derived != pubkey_hex:
        raise ValueError("pubkey_hex does not belong to privkey_hex")
    event: Dict[str, Any] = {
        "kind": 27235,
        "pubkey": pubkey_hex,
        "created_at": int(created_at if created_at is not None else time.time()),
        "tags": [["u", url], ["method", method.upper()], ["nonce", secrets.token_hex(8)]],
        "content": "",
    }
    serialized = json.dumps(
        [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    event["id"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    event["sig"] = sk.sign_schnorr(bytes.fromhex(event["id"])).hex()
    return event


def nip98_authorization(privkey_hex: str, pubkey_hex: str, url: str, method: str) -> str:
    """The Authorization header value: "Nostr <base64 event>"."""
    event = nip98_event(privkey_hex, pubkey_hex, url, method)
    return "Nostr " + base64.b64encode(json.dumps(event, separators=(",", ":")).encode("utf-8")).decode("ascii")
