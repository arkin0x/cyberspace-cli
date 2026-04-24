"""Verify ZK-STARK proofs for Cantor tree computations."""

import typer
import json
from pathlib import Path

from cyberspace_core.zk_cantor import verify_cantor_tree, verify_hyperspace_traversal, ZKCantorProof


app = typer.Typer(help="Verify ZK-STARK proofs for Cyberspace movement events.")


@app.command("cantor")
def verify_cantor(
    event_file: str = typer.Option(..., "--event", "-e", help="Nostr event JSON file"),
    proof_file: str = typer.Option(..., "--proof", "-p", help="ZK proof JSON file"),
):
    """Verify ZK proof for a Cantor tree movement (hop/sidestep)."""
    event_path = Path(event_file)
    proof_path = Path(proof_file)
    
    if not event_path.exists():
        typer.echo(f"Error: Event file not found: {event_file}")
        raise typer.Exit(1)
    
    if not proof_path.exists():
        typer.echo(f"Error: Proof file not found: {proof_file}")
        raise typer.Exit(1)
    
    with open(event_path) as f:
        event = json.load(f)
    
    with open(proof_path) as f:
        proof_data = json.load(f)
    
    # Extract leaves from event (would be in zk-leaves tag)
    leaves_tag = [t for t in event.get("tags", []) if t[0] == "zk-leaves"]
    if not leaves_tag:
        typer.echo("Error: Event missing 'zk-leaves' tag")
        raise typer.Exit(1)
    
    # Parse leaves (stored as comma-separated string)
    leaves_str = leaves_tag[0][1] if isinstance(leaves_tag[0], list) else leaves_tag
    try:
        leaves = json.loads(leaves_str)
    except json.JSONDecodeError:
        typer.echo(f"Error: zk-leaves tag is not valid JSON: {leaves_str}")
        raise typer.Exit(1)
    
    # Extract root from proof tag
    proof_tag = [t for t in event.get("tags", []) if t[0] == "proof"]
    if not proof_tag:
        typer.echo("Error: Event missing 'proof' tag")
        raise typer.Exit(1)
    
    root = int(proof_tag[0][1], 16) if isinstance(proof_tag[0], list) else int(proof_tag[0], 16)
    
    # Reconstruct proof object
    proof = ZKCantorProof(
        root=root,
        leaf_count=proof_data["leaf_count"],
        stark_proof=bytes.fromhex(proof_data["stark_proof"]),
        constraint_count=proof_data["constraint_count"],
    )
    
    # Verify
    if verify_cantor_tree(root, leaves, proof):
        typer.echo("✓ ZK proof is valid")
        raise typer.Exit(0)
    else:
        typer.echo("✗ ZK proof is invalid")
        raise typer.Exit(1)


@app.command("hyperjump")
def verify_hyperjump(
    event_file: str = typer.Option(..., "--event", "-e", help="Nostr event JSON file"),
    proof_file: str = typer.Option(..., "--proof", "-p", help="ZK proof JSON file"),
):
    """Verify ZK proof for a hyperspace traversal (hyperjump)."""
    event_path = Path(event_file)
    proof_path = Path(proof_file)
    
    if not event_path.exists():
        typer.echo(f"Error: Event file not found: {event_file}")
        raise typer.Exit(1)
    
    if not proof_path.exists():
        typer.echo(f"Error: Proof file not found: {proof_file}")
        raise typer.Exit(1)
    
    with open(event_path) as f:
        event = json.load(f)
    
    with open(proof_path) as f:
        proof_data = json.load(f)
    
    # Extract hyperjump parameters from tags
    tags_dict = {t[0]: t[1] for t in event.get("tags", []) if isinstance(t, list) and len(t) >= 2}
    
    from_height = int(tags_dict.get("from_height", "0"))
    to_height = int(tags_dict.get("B", "0"))
    prev_event_id_hex = tags_dict.get("prev", "")
    proof_hex = tags_dict.get("proof", "0")
    
    if not prev_event_id_hex:
        typer.echo("Error: Event missing 'prev' tag")
        raise typer.Exit(1)
    
    prev_event_id = bytes.fromhex(prev_event_id_hex)
    root = int(proof_hex, 16)
    
    # Reconstruct proof object
    proof = ZKCantorProof(
        root=root,
        leaf_count=proof_data["leaf_count"],
        stark_proof=bytes.fromhex(proof_data["stark_proof"]),
        constraint_count=proof_data["constraint_count"],
    )
    
    # Verify hyperspace traversal proof
    if verify_hyperspace_traversal(root, prev_event_id, from_height, to_height, proof):
        typer.echo("✓ Hyperspace ZK proof is valid")
        raise typer.Exit(0)
    else:
        typer.echo("✗ Hyperspace ZK proof is invalid")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
