#!/usr/bin/env python3
"""Test script to verify Nostr relay listener integration.

This script tests:
1. NostrRelayListener can be instantiated
2. Zap request creation and signing works
3. Cloud compute flow imports correctly
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from cyberspace_cli.nostr_relay import NostrRelayListener
from cyberspace_cli.cloud_compute import HosakaClient
from cyberspace_cli.nostr_event import new_event, sign_event
import time

def test_nostr_relay_listener():
    """Test NostrRelayListener instantiation and configuration."""
    print("Testing NostrRelayListener...")
    
    listener = NostrRelayListener()
    assert len(listener.relays) > 0, "Should have default relays"
    assert listener.HOSAKA_PUBKEY, "Should have HOSAKA pubkey"
    
    print(f"  ✓ Created with {len(listener.relays)} relays")
    print(f"  ✓ HOSAKA pubkey: {listener.HOSAKA_PUBKEY[:16]}...")
    
    # Test with custom relays
    custom_relays = ["wss://test.relay.io"]
    listener2 = NostrRelayListener(relays=custom_relays)
    assert listener2.relays == custom_relays, "Should use custom relays"
    print(f"  ✓ Custom relays work")
    
    return True

def test_zap_request_creation():
    """Test creating and signing a kind 9734 zap request."""
    print("\nTesting zap request creation...")
    
    # Test keys (not real)
    privkey = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    pubkey = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    job_id = "test-job-123"
    amount_msats = 1000
    
    # Create zap request
    created_at = int(time.time())
    zap_tags = [
        ["p", HosakaClient.HOSAKA_PUBKEY],
        ["amount", str(amount_msats)],
        ["relays", "wss://relay.damus.io"],
        ["job_id", job_id],
    ]
    
    zap_request = new_event(
        pubkey_hex=pubkey,
        created_at=created_at,
        kind=9734,
        tags=zap_tags,
        content="",
    )
    
    print(f"  ✓ Created kind {zap_request['kind']} event")
    assert zap_request["kind"] == 9734, "Should be kind 9734"
    
    # Sign the event
    signed = sign_event(zap_request, privkey)
    assert signed["sig"], "Should have signature"
    print(f"  ✓ Signed event (sig: {signed['sig'][:16]}...)")
    
    # Verify structure
    assert "id" in signed, "Should have event ID"
    assert "pubkey" in signed, "Should have pubkey"
    assert "created_at" in signed, "Should have created_at"
    print(f"  ✓ Event structure valid")
    
    return True

def test_hosaka_client():
    """Test HosakaClient configuration."""
    print("\nTesting HosakaClient...")
    
    # Test class constant
    assert HosakaClient.HOSAKA_PUBKEY, "Should have HOSAKA pubkey constant"
    print(f"  ✓ HOSAKA pubkey: {HosakaClient.HOSAKA_PUBKEY[:16]}...")
    
    # Test instantiation
    client = HosakaClient(
        privkey_hex="test",
        pubkey_hex="test",
    )
    print(f"  ✓ Client instantiated")
    print(f"  ✓ API URL: {client.api_url}")
    
    return True

def main():
    """Run all tests."""
    print("=" * 60)
    print("HOSAKA Payment Flow - Integration Tests")
    print("=" * 60)
    
    tests = [
        ("NostrRelayListener", test_nostr_relay_listener),
        ("Zap Request Creation", test_zap_request_creation),
        ("HosakaClient", test_hosaka_client),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"\n❌ {name} FAILED: {e}")
            failed += 1
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\n✅ All integration tests passed!")
        print("\nNext steps:")
        print("1. Run: cyberspace move --by 100000,0,0")
        print("2. Pay the displayed invoice")
        print("3. Watch for zap receipt detection")
        print("4. Verify job completes automatically")
        sys.exit(0)

if __name__ == "__main__":
    main()
