"""
Build configuration for the _merkle_engine C extension.

Usage:
    # From the repo root:
    python src/cyberspace_core/_merkle_engine_setup.py build_ext --inplace

    # Or manually with gcc:
    gcc -O3 -shared -fPIC -DOPENSSL_SUPPRESS_DEPRECATED \
        -I$(python3 -c "import sysconfig; print(sysconfig.get_path('include'))") \
        -lssl -lcrypto \
        -o src/cyberspace_core/_merkle_engine$(python3-config --extension-suffix) \
        src/cyberspace_core/_merkle_engine.c

    # If libssl-dev is not installed but libcrypto.so.3 exists:
    gcc -O3 -shared -fPIC -DOPENSSL_SUPPRESS_DEPRECATED \
        -I$(python3 -c "import sysconfig; print(sysconfig.get_path('include'))") \
        -o src/cyberspace_core/_merkle_engine$(python3-config --extension-suffix) \
        src/cyberspace_core/_merkle_engine.c \
        /usr/lib/x86_64-linux-gnu/libcrypto.so.3
"""

from setuptools import setup, Extension
import os

src_dir = os.path.dirname(os.path.abspath(__file__))

merkle_engine = Extension(
    "cyberspace_core._merkle_engine",
    sources=[os.path.join(src_dir, "_merkle_engine.c")],
    libraries=["ssl", "crypto"],
    extra_compile_args=["-O3", "-DOPENSSL_SUPPRESS_DEPRECATED"],
)

setup(
    name="cyberspace_core._merkle_engine",
    version="1.0",
    description="Fast Merkle tree computation for Cyberspace sidestep proofs",
    ext_modules=[merkle_engine],
)
