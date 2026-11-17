"""CLI commands dispatch to the intended coroutine (IMPLEMENT Phase 5)."""

from __future__ import annotations

import sys
from typing import Any

import pytest
from app import cli
from app.core.config import Settings


def test_retention_command_runs_the_retention_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing definition used to make ``retention`` die with a NameError."""
    seen: dict[str, Any] = {}

    async def fake_job(settings: Settings, *, dry_run: bool) -> int:
        seen["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli, "retention_job", fake_job)
    monkeypatch.setattr(sys, "argv", ["app.cli", "retention", "--dry-run"])
    with pytest.raises(SystemExit) as raised:
        cli.main()
    assert raised.value.code == 0
    assert seen == {"dry_run": True}
