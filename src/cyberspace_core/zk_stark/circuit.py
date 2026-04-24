"""Arithmetic circuit for Cantor pairing function.

This module defines the constraint system for proving correct computation
of the Cantor pairing function: π(x,y) = ((x+y)(x+y+1))/2 + y

The circuit uses 5 constraints per pairing:
1. s = x + y
2. t = s + 1
3. u = s * t
4. v = u / 2 (field division)
5. result = v + y

For a binary Cantor tree with N leaves, total constraints = 5 × (N - 1)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional


# Field modulus for STARK arithmetic
# Using a 256-bit prime compatible with common STARK implementations
FIELD_MODULUS = (1 << 256) - (1 << 32) + 1


@dataclass
class CantorCircuitTrace:
    """Execution trace for a single Cantor pairing operation.
    
    Attributes:
        x: First input value
        y: Second input value
        s: Intermediate: x + y
        t: Intermediate: s + 1
        u: Intermediate: s * t
        v: Intermediate: u / 2
        result: Final output: v + y
    """
    x: int
    y: int
    s: int
    t: int
    u: int
    v: int
    result: int


def mod_inverse(a: int, p: int) -> int:
    """Compute modular multiplicative inverse using extended Euclidean algorithm.
    
    Args:
        a: Value to invert
        p: Prime modulus
        
    Returns:
        a^(-1) mod p
        
    Raises:
        ValueError: If inverse doesn't exist (a and p not coprime)
    """
    def extended_gcd(a: int, b: int) -> Tuple[int, int, int]:
        if a == 0:
            return b, 0, 1
        gcd, x1, y1 = extended_gcd(b % a, a)
        x = y1 - (b // a) * x1
        y = x1
        return gcd, x, y
    
    if a % p == 0:
        raise ValueError(f"No modular inverse exists for {a} mod {p}")
    
    _, x, _ = extended_gcd(a % p, p)
    return (x % p + p) % p


def cantor_circuit_forward(
    x: int,
    y: int,
    field_mod: int = FIELD_MODULUS,
) -> CantorCircuitTrace:
    """Execute Cantor pairing circuit, tracking all intermediate values.
    
    This is the prover's execution trace. The STARK proof would demonstrate
    that this trace satisfies all circuit constraints without revealing
    the intermediate values.
    
    Args:
        x: First input coordinate
        y: Second input coordinate
        field_mod: Field modulus for arithmetic
        
    Returns:
        Execution trace with all intermediate values
    """
    # Constraint 1: s = x + y
    s = (x + y) % field_mod
    
    # Constraint 2: t = s + 1
    t = (s + 1) % field_mod
    
    # Constraint 3: u = s * t
    u = (s * t) % field_mod
    
    # Constraint 4: v = u / 2 (multiply by inverse of 2)
    inv_2 = mod_inverse(2, field_mod)
    v = (u * inv_2) % field_mod
    
    # Constraint 5: result = v + y
    result = (v + y) % field_mod
    
    return CantorCircuitTrace(x=x, y=y, s=s, t=t, u=u, v=v, result=result)


def cantor_direct(x: int, y: int) -> int:
    """Direct Cantor pairing computation (for verification).
    
    This is the standard formula without circuit overhead.
    Used to verify circuit correctness.
    
    Args:
        x: First input
        y: Second input
        
    Returns:
        π(x, y) = ((x+y)(x+y+1))/2 + y
    """
    s = x + y
    return (s * (s + 1)) // 2 + y


def verify_circuit_constraints(
    trace: CantorCircuitTrace,
    field_mod: int = FIELD_MODULUS,
) -> Tuple[bool, List[str]]:
    """Verify all circuit constraints are satisfied.
    
    This is what the STARK verifier would check (implicitly via the proof).
    
    Args:
        trace: Execution trace to verify
        field_mod: Field modulus
        
    Returns:
        Tuple of (is_valid, list_of_violation_messages)
    """
    violations = []
    
    # Constraint 1: s = x + y
    expected_s = (trace.x + trace.y) % field_mod
    if trace.s != expected_s:
        violations.append(
            f"C1 (s=x+y) failed: got s={trace.s}, expected {expected_s}"
        )
    
    # Constraint 2: t = s + 1
    expected_t = (trace.s + 1) % field_mod
    if trace.t != expected_t:
        violations.append(
            f"C2 (t=s+1) failed: got t={trace.t}, expected {expected_t}"
        )
    
    # Constraint 3: u = s * t
    expected_u = (trace.s * trace.t) % field_mod
    if trace.u != expected_u:
        violations.append(
            f"C3 (u=s*t) failed: got u={trace.u}, expected {expected_u}"
        )
    
    # Constraint 4: v = u / 2
    inv_2 = mod_inverse(2, field_mod)
    expected_v = (trace.u * inv_2) % field_mod
    if trace.v != expected_v:
        violations.append(
            f"C4 (v=u/2) failed: got v={trace.v}, expected {expected_v}"
        )
    
    # Constraint 5: result = v + y
    expected_result = (trace.v + trace.y) % field_mod
    if trace.result != expected_result:
        violations.append(
            f"C5 (result=v+y) failed: got result={trace.result}, expected {expected_result}"
        )
    
    # Sanity check: result should match direct computation
    direct_result = cantor_direct(trace.x, trace.y) % field_mod
    if trace.result != direct_result:
        violations.append(
            f"Result mismatch with direct computation: "
            f"circuit={trace.result}, direct={direct_result}"
        )
    
    return len(violations) == 0, violations


@dataclass
class CantorTreeTrace:
    """Execution trace for a full Cantor pairing tree.
    
    For a tree with N leaves, this contains N-1 CantorCircuitTrace objects,
    one for each pairing operation in the tree.
    
    Attributes:
        leaves: Input leaf values
        traces: Execution trace for each pairing (in level order)
        root: Final tree root
    """
    leaves: List[int]
    traces: List[CantorCircuitTrace]
    root: int


def cantor_tree_circuit(
    leaves: List[int],
    field_mod: int = FIELD_MODULUS,
) -> CantorTreeTrace:
    """Build Cantor tree execution trace for multiple leaves.
    
    Args:
        leaves: List of leaf values (coordinates, temporal seed, etc.)
        field_mod: Field modulus
        
    Returns:
        Full tree trace with all intermediate pairing traces
        
    Raises:
        ValueError: If leaves list is empty
    """
    if not leaves:
        raise ValueError("Cannot build Cantor tree over empty leaf list")
    
    if len(leaves) == 1:
        # Trivial tree - no pairing needed
        return CantorTreeTrace(
            leaves=leaves,
            traces=[],
            root=leaves[0] % field_mod,
        )
    
    all_traces: List[CantorCircuitTrace] = []
    current_level = [(x % field_mod) for x in leaves]
    
    while len(current_level) > 1:
        next_level = []
        
        for i in range(0, len(current_level) - 1, 2):
            x, y = current_level[i], current_level[i + 1]
            trace = cantor_circuit_forward(x, y, field_mod)
            all_traces.append(trace)
            next_level.append(trace.result)
        
        # Carry forward unpaired leaf
        if len(current_level) % 2 == 1:
            next_level.append(current_level[-1])
        
        current_level = next_level
    
    return CantorTreeTrace(
        leaves=[x % field_mod for x in leaves],
        traces=all_traces,
        root=current_level[0],
    )


def verify_tree_constraints(
    tree_trace: CantorTreeTrace,
    field_mod: int = FIELD_MODULUS,
) -> Tuple[bool, List[str]]:
    """Verify all constraints in a Cantor tree trace.
    
    Args:
        tree_trace: Tree execution trace
        field_mod: Field modulus
        
    Returns:
        Tuple of (is_valid, list_of_violation_messages)
    """
    all_violations = []
    
    # Verify each pairing trace
    for i, trace in enumerate(tree_trace.traces):
        is_valid, violations = verify_circuit_constraints(trace, field_mod)
        if not is_valid:
            all_violations.extend(
                [f"Pairing #{i}: {v}" for v in violations]
            )
    
    # Verify tree structure: last trace result should equal root
    if tree_trace.traces:
        expected_root = tree_trace.traces[-1].result
        if tree_trace.root != expected_root:
            all_violations.append(
                f"Root mismatch: trace root={expected_root}, "
                f"tree root={tree_trace.root}"
            )
    
    return len(all_violations) == 0, all_violations


# Convenience function for constraint counting
def count_constraints(num_leaves: int) -> dict:
    """Calculate constraint counts for a Cantor tree.
    
    Args:
        num_leaves: Number of leaves in tree
        
    Returns:
        Dictionary with constraint statistics
    """
    if num_leaves < 1:
        return {
            "num_leaves": 0,
            "num_pairings": 0,
            "total_constraints": 0,
            "constraints_per_pairing": 5,
        }
    
    num_pairings = num_leaves - 1
    total_constraints = 5 * num_pairings
    
    return {
        "num_leaves": num_leaves,
        "num_pairings": num_pairings,
        "total_constraints": total_constraints,
        "constraints_per_pairing": 5,
    }
