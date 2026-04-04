import time
from cyberspace_core.movement import compute_axis_merkle_root_streaming

for h in [16, 17, 18, 19, 20, 22, 25]:
    start = time.time()
    root, siblings = compute_axis_merkle_root_streaming(0, h)
    elapsed = time.time() - start
    print(f'LCA {h}: {elapsed:.2f}s ({2**h} leaves)')
