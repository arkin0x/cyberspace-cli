"""Nostr NIP-98 signing utilities for cyberspace-cli.

Provides functions to sign HTTP requests per NIP-98 spec.
Used by HOSAKA cloud compute integration.
"""
import base64
import hashlib
import json
import time
from typing import Optional, List, Dict, Any

try:
    from secp256k1 import PrivateKey
    HAS_SECP = True
except ImportError:
    HAS_SECP = False


def sign_event(event: Dict[str, Any], privkey_hex: str) -> Dict[str, Any]:
    """Sign any Nostr event using Schnorr signature.
    
    Args:
        event: Event dict with 'id' already computed
        privkey_hex: Private key in hex format
    
    Returns:
        Event dict with 'sig' field populated
    
    Works for any event kind: 9734 (zap request), 27235 (NIP-98), etc.
    Per NIP-01, signature is Schnorr signature of the event ID.
    """
    if not HAS_SECP:
        raise ImportError("secp256k1 package required for signing. Install with: pip install secp256k1")
    
    # Private key
    seckey = PrivateKey(bytes.fromhex(privkey_hex), raw=True)
    
    # Event ID is already computed - sign it
    event_id_bytes = bytes.fromhex(event['id'])
    
    # Schnorr sign (no double-hash - the event ID is already SHA256)
    sig = seckey.schnorr_sign(event_id_bytes, raw=True)
    
    # Add signature to event
    event['sig'] = sig.hex()
    return event


def sign_nip98_request(
    privkey_hex: str,
    pubkey_hex: str,
    url: str,
    method: str = "POST",
    body_hash: Optional[str] = None,
) -> str:
    """Sign an HTTP request per NIP-98 spec.
    
    Args:
        privkey_hex: Private key (hex) - kept secret
        pubkey_hex: Public key (hex)
        url: Full URL being requested
        method: HTTP method (GET, POST, etc.)
        body_hash: Optional SHA256 hash of request body
    
    Returns:
        Authorization header value: "Nostr <base64(event)>"
    """
    if not HAS_SECP:
        raise ImportError("secp256k1 required for NIP-98 signing")
    
    created_at = int(time.time())
    
    # Build tags
    tags: List[List[str]] = [
        ["u", url],
        ["method", method],
    ]
    
    # Add body hash if provided
    if body_hash:
        tags.append(["h", body_hash])
    
    # Create event ID
    event_data = [
        0,
        pubkey_hex,
        created_at,
        27235,  # kind 27235 = HTTP auth
        tags,
        "",  # content (empty for basic auth)
    ]
    serialized = json.dumps(event_data, separators=(",", ":"))
    event_id = hashlib.sha256(serialized.encode()).hexdigest()
    
    # Sign with private key
    sk = PrivateKey(bytes.fromhex(privkey_hex), raw=True)
    sig = sk.schnorr_sign(bytes.fromhex(event_id), bip340tag=None, raw=True)
    sig_hex = sig.hex()
    
    # Build event
    event = {
        "id": event_id,
        "kind": 27235,
        "pubkey": pubkey_hex,
        "created_at": created_at,
        "tags": tags,
        "content": "",
        "sig": sig_hex,
    }
    
    # Encode as Authorization header
    event_json = json.dumps(event, separators=(",", ":"))
    event_b64 = base64.b64encode(event_json.encode()).decode()
    return f"Nostr {event_b64}"


def create_nip98_auth_header(
    privkey_hex: str,
    pubkey_hex: str,
    url: str,
    method: str = "GET",
    body: Optional[bytes] = None,
) -> Dict[str, str]:
    """Create Authorization header dict for HTTP request.
    
    Args:
        privkey_hex: Private key (hex)
        pubkey_hex: Public key (hex)
        url: Full URL
        method: HTTP method
        body: Optional request body (will be hashed)
    
    Returns:
        Dict: {"Authorization": "Nostr <base64(event)>"}
    """
    body_hash = None
    if body:
        body_hash = hashlib.sha256(body).hexdigest()
    
    auth_value = sign_nip98_request(
        privkey_hex=privkey_hex,
        pubkey_hex=pubkey_hex,
        url=url,
        method=method,
        body_hash=body_hash,
    )
    
    return {"Authorization": auth_value}
