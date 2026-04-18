# ZK-STARK proofs for Cyberspace Cantor tree verification
# 
# This module provides zero-knowledge proof generation and verification
# for Cantor pairing tree computations, enabling lightweight client verification.
#
# Status: Experimental / Proof-of-Concept
# See: docs/ZK_STARK_DESIGN.md for full specification

from .circuit import (
    CantorCircuitTrace,
    cantor_circuit_forward,
    cantor_direct,
    verify_circuit_constraints,
    mod_inverse,
    FIELD_MODULUS,
)

__all__ = [
    "CantorCircuitTrace",
    "cantor_circuit_forward",
    "cantor_direct",
    "verify_circuit_constraints",
    "mod_inverse",
    "FIELD_MODULUS",
]
