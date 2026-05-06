# PR 12 design notes (archive)

These markdown files were produced during the original HOSAKA integration
PR (`#12`, branch `feature/hosaka-integration`) and describe an earlier
design iteration of the cloud-compute flow:

- per-axis Cantor jobs submitted via `POST /api/v1/jobs`
- region_n composed via `POST /api/v1/cantor/compose-region`
- CLI downloaded `region_n` and computed `proof_hash = sha256(sha256(region_n))`
  locally — which is **incorrect** because it omits the temporal axis (§5.6
  requires `hop_n = π(region_n, cantor_t)` and `proof_hash = sha256(sha256(hop_n))`)

That whole flow was replaced in this branch by the encapsulated
`POST /api/v1/hop` endpoint, which runs the §4.7 + §5 pipeline server-side
and returns `proof_hash` directly. The notes here are kept only as a
historical reference for what was tried and why we changed direction; do
not treat them as authoritative documentation of the current behavior.

For the current design see:
- `~/repos/hosaka-api/docs/CANTOR_STORAGE_GUIDE.md` — file storage layout,
  endpoints, retention, follow-ups.
- `~/repos/cyberspace/CYBERSPACE_V2.md` — protocol spec.
- `src/cyberspace_cli/cloud_compute.py` — current CLI integration.
