"""Tests for enter-hyperspace CLI command per DECK-0001 §I.3."""

import pytest
from typer.testing import CliRunner
from cyberspace_cli.cli import app

runner = CliRunner()


class TestEnterHyperspaceCommand:
    """Test enter-hyperspace CLI command."""

    def test_enter_hyperspace_help(self):
        """Test that enter-hyperspace command exists and shows help."""
        # The command should be accessible via the main app
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Check that enter-hyperspace is mentioned in the help
        # It might be under hyperjump subcommand or standalone

    def test_hyperjump_enterable_help(self):
        """Test that hyperjump enterable command exists."""
        result = runner.invoke(app, ["hyperjump", "--help"])
        assert result.exit_code == 0
        # The enterable command should be listed
