"""Integration tests for ZK-STARK proof workflow.

These tests verify end-to-end functionality from proof generation to verification.
"""

import unittest
import os
import json
import tempfile
from pathlib import Path

from cyberspace_core.zk_cantor import (
    prove_hyperspace_traversal,
    verify_hyperspace_traversal,
    ZKCantorProof,
)


class TestZKIntegration(unittest.TestCase):
    """Integration tests for zk-STARK proof generation and verification."""
    
    def test_hyperjump_zk_workflow(self):
        """Test complete hyperjump ZK proof workflow"""
        # Generate proof
        prev_id = os.urandom(32)
        root, proof = prove_hyperspace_traversal(prev_id, 1606, 1607)
        
        # Verify proof properties
        self.assertEqual(proof.leaf_count, 3)  # temporal_seed + 1606 + 1607
        self.assertGreater(len(proof.stark_proof), 0)
        self.assertGreater(proof.constraint_count, 0)
        
        # Verify the proof
        is_valid = verify_hyperspace_traversal(
            root, prev_id, 1606, 1607, proof
        )
        self.assertTrue(is_valid)
    
    def test_multi_block_hyperjump_zk(self):
        """Test ZK proof for 100-block hyperspace traversal"""
        prev_id = os.urandom(32)
        from_height, to_height = 850000, 850100
        
        root, proof = prove_hyperspace_traversal(prev_id, from_height, to_height)
        
        # Should have 102 leaves: temporal_seed + 101 block heights
        self.assertEqual(proof.leaf_count, 102)
        
        # Verify
        is_valid = verify_hyperspace_traversal(
            root, prev_id, from_height, to_height, proof
        )
        self.assertTrue(is_valid)
    
    def test_proof_serialization_roundtrip(self):
        """Test that proofs can be serialized and deserialized"""
        prev_id = os.urandom(32)
        root, proof = prove_hyperspace_traversal(prev_id, 1606, 1607)
        
        # Serialize to JSON-compatible dict
        proof_dict = {
            "root": f"0x{root:064x}",
            "leaf_count": proof.leaf_count,
            "stark_proof": proof.stark_proof.hex(),
            "constraint_count": proof.constraint_count,
        }
        
        # Deserialize
        reconstructed = ZKCantorProof(
            root=proof_dict["root"] if not isinstance(proof_dict["root"], str) else int(proof_dict["root"], 16),
            leaf_count=proof_dict["leaf_count"],
            stark_proof=bytes.fromhex(proof_dict["stark_proof"]),
            constraint_count=proof_dict["constraint_count"],
        )
        
        # Verify reconstructed proof
        is_valid = verify_hyperspace_traversal(
            root, prev_id, 1606, 1607, reconstructed
        )
        self.assertTrue(is_valid)


class TestCLIIntegration(unittest.TestCase):
    """Integration tests for CLI commands."""
    
    def test_verify_zk_command_structure(self):
        """Test that verify-zk CLI commands are callable"""
        from cyberspace_cli.commands.verify_zk import app
        from typer.testing import CliRunner
        
        runner = CliRunner()
        
        # Test cantor subcommand help
        result = runner.invoke(app, ["cantor", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Verify ZK proof for a Cantor tree movement", result.output)
        
        # Test hyperjump subcommand help
        result = runner.invoke(app, ["hyperjump", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Verify ZK proof for a hyperspace traversal", result.output)
    
    # Note: Full end-to-end CLI tests would require actual Nostr events.
    # These are integration stubs to verify command structure.


if __name__ == "__main__":
    unittest.main()
