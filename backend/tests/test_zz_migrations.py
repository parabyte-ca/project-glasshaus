"""Runs last (file order): a full downgrade invalidates cached type OIDs in pooled connections."""

import pytest

from glasshaus.cli import main as cli

pytestmark = pytest.mark.integration


def test_migrate_up_down_up() -> None:
    cli(["migrate"])
    cli(["downgrade", "base"])
    cli(["migrate"])
