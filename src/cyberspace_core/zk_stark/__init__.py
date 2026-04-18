# ZK-STARK proofs for Cyberspace Cantor tree verification
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

from .proof import (
    CantorZKPublicInputs,
    CantorZKProof,
    prove_cantor_single_pair,
    prove_cantor_tree,
    verify_cantor_proof,
    verify_proof_timing,
    add_zk_tags_to_event,
    extract_zk_proof_from_event,
    benchmark_proof_generation,
    benchmark_verification,
)

__all__ = [
    # Circuit layer
    "CantorCircuitTrace",
    "cantor_circuit_forward",
    "cantor_direct",
    "verify_circuit_constraints",
    "mod_inverse",
    "FIELD_MODULUS",
    # Proof layer
    "CantorZKPublicInputs",
    "CantorZKProof",
    "prove_cantor_single_pair",
    "prove_cantor_tree",
    "verify_cantor_proof",
    "verify_proof_timing",
    "add_zk_tags_to_event",
    "extract_zk_proof_from_event",
    "benchmark_proof_generation",
    "benchmark_verification",
]
