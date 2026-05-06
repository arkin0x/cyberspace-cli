# HOSAKA Payment Flow - User Guide

## Quick Start

Run a movement that requires cloud compute:

```bash
cyberspace move --by 100000,0,0
```

## What Happens

1. **LCA Detection**: CLI detects the movement requires height > local limit
2. **Estimate**: Shows cost estimate (e.g., "667 sats ($0.50)")
3. **Confirmation**: Asks if you want to proceed
4. **Job Submission**: Creates a pending job on HOSAKA API
5. **Invoice Generation**: Gets Lightning invoice from Strike
6. **QR Display**: Shows QR code for payment
7. **Auto-Detection**: **Listens on Nostr relays for payment receipt**
8. **Auto-Redemption**: **Automatically credits your balance**
9. **Compute Starts**: **Job transitions to "computing" status**
10. **Polling**: Waits for cloud compute to complete
11. **Result**: Returns proof to cyberspace-cli

## Payment Flow Diagram

```
User: cyberspace move --by 100000,0,0
   │
   ├─ CLI: Detects LCA height needed
   ├─ CLI: Shows estimate, asks for confirmation
   ├─ User: Confirms (Y)
   │
   ├─ CLI: Submits job → API (status: PENDING)
   ├─ CLI: Requests invoice from Strike
   ├─ Strike: Returns bolt11 invoice
   │
   ├─ CLI: Creates kind 9734 zap request
   ├─ CLI: Signs with Nostr key
   ├─ CLI: Sends to Strike LNURL callback
   ├─ Strike: Returns bolt11
   │
   ├─ CLI: Displays QR code
   ├─ CLI: Starts listening on Nostr relays
   │
   ├─ User: Pays invoice with Lightning wallet
   │
   ├─ Strike: Broadcasts kind 9735 zap receipt
   ├─ Relays: Propagate receipt
   │
   ├─ CLI: Detects receipt on relay
   ├─ CLI: POSTs receipt to /api/v1/deposit/redeem
   ├─ API: Validates receipt
   ├─ API: Credits user balance
   ├─ API: Marks job as COMPUTING
   ├─ API: Triggers Modal compute
   │
   ├─ Modal: Runs compute function
   ├─ Modal: Returns proof
   │
   ├─ API: Updates job status to COMPLETED
   ├─ CLI: Polls job status
   ├─ CLI: Receives proof
   │
   └─ Done! Proof appended to chain
```

## Troubleshooting

### Payment Not Detected

If you paid but the CLI shows "Payment detection timed out":

1. **Check your wallet**: Ensure it supports NIP-57 zaps (Strike, Blink, Zebedee do)
2. **Wait**: Receipts can take a few seconds to propagate
3. **Retry**: The receipt may still be valid for manual redemption
4. **Manual redemption**: Contact support with payment receipt

### Common Issues

**"Failed to sign zap request"**
- Ensure your Nostr key is properly configured in cyberspace-cli

**"Failed to get bolt11 invoice"**
- Check internet connection
- Strike service may be temporarily unavailable

**"Payment detection timed out"**
- Your wallet may not support NIP-57 zaps
- Try a different Lightning wallet (Strike recommended)

## Supported Wallets

The following wallets support NIP-57 zaps:
- ✅ Strike (recommended)
- ✅ Blink
- ✅ Zebedee
- ✅ Wallet of Satoshi
- ⚠️  Other wallets: May work if they support NIP-57

## Costs

| Tier | Height Range | Cost (USD) | Cost (sats) | Time |
|------|--------------|------------|-------------|------|
| Micro | h=20-22 | $0.05 | 7 sats | <5 sec |
| Small | h=23-25 | $0.25 | 33 sats | 5-60 sec |
| Medium | h=26-28 | $1.00 | 133 sats | 1-5 min |
| Large | h=29-32 | $5.00 | 667 sats | 5-30 min |
| XLarge | h=33-35 | $25.00 | 3,333 sats | 30 min-2 hr |

*Prices based on BTC @ $75,000*

## Technical Details

### Nostr Relays Monitored

The CLI listens on these relays for zap receipts:
- wss://relay.damus.io
- wss://nos.lol
- wss://relay.nostr.band
- wss://purplepag.es
- wss://relay.snort.social

### Zap Request Format

```json
{
  "kind": 9734,
  "tags": [
    ["p", "e8ed3798..."],  // HOSAKA pubkey
    ["amount", "667000"],
    ["relays", "wss://relay.damus.io", ...],
    ["job_id", "uuid-here"]  // Custom tracking tag
  ],
  "content": "",
  "pubkey": "<your pubkey>",
  "sig": "<signature>"
}
```

### Zap Receipt Format (from Strike)

```json
{
  "kind": 9735,
  "tags": [
    ["p", "e8ed3798..."],  // HOSAKA pubkey
    ["bolt11", "lnbc..."],
    ["description", "<zap request JSON>"],
    ["job_id", "uuid-here"]  // Extracted from description
  ],
  "content": "",
  "pubkey": "<payer pubkey>",
  "sig": "<signature>"
}
```

## Security

- **Private keys never leave your machine**: Signing is done locally
- **NIP-98 authentication**: All API requests are signed
- **Receipt validation**: API verifies receipt signatures before crediting
- **Pubkey scoping**: You can only access your own jobs and balance

## Support

For issues or questions:
1. Check this guide first
2. Review error messages carefully
3. Contact: arkin0x@strike.me (Nostr DMs open)

---

**Happy Cyberspace Navigation! 🚀**
