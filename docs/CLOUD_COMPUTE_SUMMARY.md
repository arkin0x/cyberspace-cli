# Quick Summary: Cloud Hosting Research

**Date:** 2026-04-17  
**Full report:** `docs/CLOUD_COMPUTE_RESEARCH.md`

---

## ⭐ Recommendation: Modal.com

**Why:** Serverless, Python-native, perfect cost/performance, easiest integration

### Pricing

| LCA Height | A100 Time | Cost |
|------------|-----------|------|
| h=25 | 1s | $0.0003 |
| h=28 | 8s | $0.002 |
| h=30 | 30s | $0.009 |
| h=32 | 2min | $0.035 |
| h=35 | 15min | $0.28 |

**Your likely usage:**
- Casual (10/month, h=28): **$0.08/month**
- Active (100/month, h=30): **$0.90/month**
- Power (1000/month, h=32): **$35/month**

---

## Implementation Plan

### This Week
1. Set up Modal account
2. Create `src/cyberspace_cli/cloud/modal_client.py`
3. Add `--cloud` flag to move command
4. Test with h=28-30 proofs

### Cost Controls
- Default max: $1.00/job
- Daily limit: $10.00
- User confirm for jobs >$0.50

### Commercial Potential
**If we sell access:**
- Cost: ~$200/month (10k proofs)
- Revenue: ~$500/month (at $0.05 markup)
- **Profit: 60% margin**

---

## Next Actions

1. **You decide:** Modal account email? (arkin0x@gmail.com or dedicated?)
2. **Budget:** Max cost per proof before confirmation? (suggest $0.10)
3. **Priority:** Personal use first vs commercial platform?

I'll start implementing the Modal integration code now while you review.

---

## Files Created

- `docs/CLOUD_COMPUTE_RESEARCH.md` — Full detailed report
- `docs/EARTH_TRAVERSAL_PLAN.md` — Earth traversal strategy (coming next)
