"""Nostr relay listener for zap receipts.

Listens on Nostr relays for kind 9735 zap receipts that reference jobs we created.
When a receipt is detected, extracts the payment info and triggers redemption.
"""
import asyncio
import json
import random
import time
from typing import Callable, Dict, List, Optional
from websocket import create_connection


class NostrRelayListener:
    """Subscribe to Nostr relays and listen for specific events."""
    
    # Default relays for zap receipt detection
    DEFAULT_RELAYS = [
        "wss://relay.damus.io",
        "wss://nos.lol",
        "wss://relay.nostr.band",
        "wss://purplepag.es",
        "wss://relay.snort.social",
    ]
    
    # HOSAKA's Nostr pubkey (from Strike: arkin0x@strike.me)
    HOSAKA_PUBKEY = "e8ed3798c6ffebffa08501ac39e271662bfd160f688f94c45d692d8767dd345a"
    
    def __init__(self, relays: Optional[List[str]] = None):
        self.relays = relays or self.DEFAULT_RELAYS
        self.found_receipt = None
        self.found_event = None
    
    async def subscribe_to_zap_receipts(
        self,
        job_id: str,
        user_pubkey: str,
        callback: Callable[[dict], None],
        timeout: int = 300,  # 5 minutes
    ) -> bool:
        """Listen for zap receipts matching job_id.
        
        Args:
            job_id: The job ID we're waiting for payment on
            user_pubkey: The user's pubkey (payer)
            callback: Function to call when receipt is found
            timeout: Seconds to listen before giving up
        
        Returns:
            True if receipt found, False if timeout
        
        NIP-57 Zap Receipt (kind 9735) structure:
        {
            "kind": 9735,
            "tags": [
                ["p", "<recipient_pubkey>"],      # HOSAKA's npub
                ["bolt11", "<invoice>"],           # The paid invoice
                ["description", "<zap_request>"],  # JSON string of kind 9734
                ["e", "<event_id>"],               # Optional: job_id if included
                ...
            ],
            "content": "",
            "pubkey": "<payer_pubkey>",
            "created_at": <timestamp>,
            "sig": "<signature>"
        }
        
        Filter:
        - kind=9735
        - #p = HOSAKA npub (to ensure receipt is for us)
        - Check description tag for job_id match
        """
        start_time = time.time()
        self.found_receipt = None
        
        # Build subscription filter
        filter_dict = {
            "kinds": [9735],
            "#p": [self.HOSAKA_PUBKEY],  # HOSAKA's npub
            "since": int(start_time) - 60,  # Last 60 seconds
        }
        
        # Connect to relays and subscribe
        tasks = []
        for relay_url in self.relays:
            task = asyncio.create_task(
                self._listen_to_relay(relay_url, filter_dict, job_id, callback, timeout)
            )
            tasks.append(task)
        
        # Wait for first receipt or timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            pass
        
        # Check if we found a receipt
        if self.found_receipt:
            return True
        return False
    
    async def _listen_to_relay(
        self,
        relay_url: str,
        filter_dict: dict,
        job_id: str,
        callback: Callable,
        timeout: int,
    ):
        """Connect to single relay and listen for matching events."""
        ws = None
        try:
            # Generate random subscription ID
            sub_id = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
            
            # Open websocket connection
            ws = create_connection(relay_url, timeout=10)
            
            # Send subscription
            subscribe_msg = json.dumps(["REQ", sub_id, filter_dict])
            ws.send(subscribe_msg)
            
            # Set timeout
            end_time = time.time() + timeout
            
            # Listen for events
            while time.time() < end_time and not self.found_receipt:
                ws.settimeout(1.0)  # 1 second timeout for recv
                try:
                    msg = ws.recv()
                    data = json.loads(msg)
                    
                    # Check if it's an EVENT message
                    if len(data) >= 3 and data[0] == "EVENT":
                        event = data[2]
                        
                        # Validate and extract job_id from event
                        extracted_job_id = self._extract_job_id_from_receipt(event)
                        
                        # If matches our job, trigger callback
                        if extracted_job_id and extracted_job_id == job_id:
                            self.found_receipt = event
                            self.found_event = event
                            await callback(event)
                            return  # Exit after finding receipt
                    
                    # Check for EOSE (end of stored events)
                    elif len(data) >= 2 and data[0] == "EOSE":
                        # No more historical events, continue listening for new ones
                        pass
                        
                except TimeoutError:
                    continue  # No new data, keep listening
                except Exception as e:
                    print(f"Error processing relay message: {e}")
                    continue
            
            # Timeout - close connection
            if ws:
                ws.close()
            
        except Exception as e:
            print(f"Relay connection error ({relay_url}): {e}")
            if ws:
                try:
                    ws.close()
                except:
                    pass
    
    def _extract_job_id_from_receipt(self, event: dict) -> Optional[str]:
        """Extract job_id from zap receipt description tag.
        
        The description tag contains the original kind 9734 zap request as JSON.
        We included the job_id in custom tags.
        """
        tags = event.get("tags", [])
        
        # Look for custom job_id tag (we'll add this when creating zap request)
        for tag in tags:
            if tag[0] == "job_id" and len(tag) >= 2:
                return tag[1]
        
        # Alternative: look in description JSON
        for tag in tags:
            if tag[0] == "description" and len(tag) >= 2:
                try:
                    desc = json.loads(tag[1])
                    if isinstance(desc, dict):
                        # Check for custom job_id tag in the zap request
                        desc_tags = desc.get("tags", [])
                        for dt in desc_tags:
                            if dt[0] == "job_id" and len(dt) >= 2:
                                return dt[1]
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
        
        return None
    
    def get_receipt(self) -> Optional[dict]:
        """Get the found receipt event."""
        return self.found_receipt
