"""Crypto commands for cyberspace-cli.

Commands: encrypt, decrypt, scan
"""
from typing import Optional, List
from pathlib import Path
import typer


def encrypt_command(
    text: Optional[str] = None,
    file: Optional[str] = None,
    height: int = 4,
    key: Optional[str] = None,
    key_hex: Optional[str] = None,
    from_coord: Optional[str] = None,
    from_xyz: Optional[str] = None,
) -> None:
    """Encrypt plaintext with location-based key."""
    from cyberspace_cli.coords import coord_to_xyz, xyz_to_coord
    from cyberspace_cli.parsing import normalize_hex_32
    from cyberspace_core.location_encryption import (
        derive_region_key_material_scan,
        derive_region_key_material_for_height,
        encrypt_with_location_key,
    )
    from cyberspace_core.cantor import sha256
    
    # Get plaintext
    if text:
        if file:
            typer.echo("Use --text XOR --file", err=True)
            raise typer.Exit(code=2)
        plaintext = text.encode("utf-8")
    elif file:
        plaintext = Path(file).read_bytes()
    else:
        typer.echo("Provide --text or --file", err=True)
        raise typer.Exit(code=2)
    
    # Get key material
    if key:
        key_material = key.encode("utf-8")
    elif key_hex:
        key_material = bytes.fromhex(key_hex)
    else:
        if not from_coord and not from_xyz:
            typer.echo("Provide --key, --key-hex, or --from-coord/--from-xyz", err=True)
            raise typer.Exit(code=2)
        
        if from_coord:
            try:
                coord_hex = normalize_hex_32(from_coord)
                coord_int = int.from_bytes(bytes.fromhex(coord_hex), "big")
                x, y, z, plane = coord_to_xyz(coord_int)
            except ValueError as e:
                raise typer.BadParameter(f"Invalid coord: {e}")
        else:
            parts = [int(p.strip()) for p in from_xyz.split(",")]
            if len(parts) != 3:
                raise typer.BadParameter("--from-xyz expects x,y,z")
            x, y, z = parts
            plane = 0
            coord_int = xyz_to_coord(x, y, z, plane)
        
        key_material = derive_region_key_material_scan(coord_int)
    
    # Derive encryption key from key material + height
    if isinstance(key_material, bytes):
        region_key = derive_region_key_material_for_height(key_material, height)
    else:
        region_key = key_material
    
    # Encrypt
    ciphertext, encryption_key = encrypt_with_location_key(plaintext, region_key)
    
    # Output
    typer.echo(f"height: {height}")
    typer.echo(f"region_key_sha256: {sha256(region_key).hex()}")
    typer.echo(f"encryption_key: {encryption_key.hex()}")
    typer.echo(f"ciphertext_hex: {ciphertext.hex()}")


def decrypt_command(
    ciphertext_hex: str,
    encryption_key_hex: str,
) -> None:
    """Decrypt ciphertext with encryption key."""
    from cyberspace_core.location_encryption import decrypt_with_location_key
    
    try:
        ciphertext = bytes.fromhex(ciphertext_hex)
        encryption_key = bytes.fromhex(encryption_key_hex)
    except ValueError as e:
        raise typer.BadParameter(f"Invalid hex: {e}")
    
    try:
        plaintext = decrypt_with_location_key(ciphertext, encryption_key)
        typer.echo(plaintext.decode("utf-8"))
    except Exception as e:
        typer.echo(f"Decryption failed: {e}", err=True)
        raise typer.Exit(code=1)


def scan_command(
    region_key_hex: str,
    target: Optional[str] = None,
    max_height: int = 15,
    output_dir: Optional[str] = None,
) -> None:
    """Scan encrypted events in a region."""
    from cyberspace_cli.parsing import normalize_hex_32
    from cyberspace_core.location_encryption import (
        DEFAULT_SCAN_MAX_HEIGHT,
        derive_region_key_material_scan,
        encrypt_with_location_key,
    )
    
    typer.echo("Scanning encrypted events...")
    typer.echo(f"(scan implementation pending - region key received)")
    typer.echo(f"region_key: {region_key_hex[:32]}...")
    typer.echo(f"target: {target}")
    typer.echo(f"max_height: {max_height}")
    
    # TODO: Implement actual scanning logic
    # This would query relay, try decryption at each height, collect matches
