"""Verification for Task 13 (automation & docs).

PyYAML is deliberately not a project dependency, so the workflow files are
checked structurally (string invariants) rather than parsed. The README's
``oracle`` command invocations are validated against the *real* click command
tree in ``oracle.cli`` so docs can't drift from the CLI.
"""

from __future__ import annotations

import re
from pathlib import Path

import click

from oracle.cli import cli

ROOT = Path(__file__).resolve().parents[1]
CRON = ROOT / ".github" / "workflows" / "oracle-cron.yml"
BRAIN = ROOT / ".github" / "workflows" / "oracle-brain.yml"
README = ROOT / "README.md"


# --------------------------------------------------------------------------- #
# files exist
# --------------------------------------------------------------------------- #
def test_task13_files_exist():
    assert CRON.is_file()
    assert BRAIN.is_file()
    assert README.is_file()


# --------------------------------------------------------------------------- #
# oracle-cron.yml — L1 ENABLED
# --------------------------------------------------------------------------- #
def test_cron_is_enabled_with_schedule_and_dispatch():
    text = CRON.read_text(encoding="utf-8")
    # A schedule trigger present and NOT commented out (enabled).
    assert re.search(r"^\s*schedule:", text, re.MULTILINE), "cron must have a schedule:"
    assert re.search(r"^\s*-\s*cron:", text, re.MULTILINE), "cron schedule must be active"
    assert "workflow_dispatch" in text


def test_cron_asserts_anthropic_key_absent():
    text = CRON.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" in text
    # The guard fails the job when the key is present.
    assert re.search(r'-n\s+"\$ANTHROPIC_API_KEY"', text)
    assert "exit 1" in text


def test_cron_uses_shared_concurrency_group():
    text = CRON.read_text(encoding="utf-8")
    assert re.search(r"group:\s*oracle-state", text)
    assert "cancel-in-progress: false" in text


def test_cron_runs_the_plumbing_steps():
    text = CRON.read_text(encoding="utf-8")
    assert "import fetch" in text and "--closes-within 14d" in text and "--auto-approve" in text
    assert "triggers due" in text
    assert "resolve --due --platform-only" in text
    assert "scoreboard --render" in text
    assert "pnl --render" in text
    assert "[oracle-cron]" in text
    assert "ORACLE_WEBHOOK_URL" in text


# --------------------------------------------------------------------------- #
# oracle-brain.yml — L2 DISABLED
# --------------------------------------------------------------------------- #
def test_brain_schedule_is_commented_out():
    text = BRAIN.read_text(encoding="utf-8")
    # No active schedule: every `schedule:` / `- cron:` line must be commented.
    for line in text.splitlines():
        stripped = line.strip()
        if "schedule:" in stripped or re.match(r"-\s*cron:", stripped):
            assert stripped.startswith("#"), f"schedule must be disabled: {line!r}"
    # But it is still runnable by hand.
    assert "workflow_dispatch" in text


def test_brain_uses_claude_action_and_oauth_token():
    text = BRAIN.read_text(encoding="utf-8")
    assert "anthropics/claude-code-action" in text
    assert "CLAUDE_CODE_OAUTH_TOKEN" in text
    # Per-run cap of 5 forecasts (§11.2).
    assert '"5"' in text or "default: 5" in text
    assert "max_forecasts" in text


def test_brain_asserts_anthropic_key_absent_and_shares_concurrency():
    text = BRAIN.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" in text
    assert "exit 1" in text
    assert re.search(r"group:\s*oracle-state", text)
    assert "cancel-in-progress: false" in text


# --------------------------------------------------------------------------- #
# README structure
# --------------------------------------------------------------------------- #
def test_readme_covers_required_sections():
    text = README.read_text(encoding="utf-8").lower()
    assert "uv sync" in text                       # install
    assert "worked example" in text                # end-to-end example
    assert "claude setup-token" in text            # enabling automation
    assert "claude_code_oauth_token" in text
    assert "adding a domain skill" in text         # collaborator docs
    # The worked example touches the whole loop.
    for cmd in ("question create", "oracle report", "oracle resolve", "oracle scoreboard"):
        assert cmd in text, f"worked example must mention {cmd!r}"


# --------------------------------------------------------------------------- #
# README commands must match the real CLI
# --------------------------------------------------------------------------- #
def _readme_oracle_invocations() -> list[str]:
    text = README.read_text(encoding="utf-8")
    blocks = re.findall(r"```(?:bash|sh)?\n(.*?)```", text, re.DOTALL)
    invs: list[str] = []
    for block in blocks:
        for line in block.splitlines():
            m = re.match(r"^\s*(?:uv run\s+)?oracle\s+(.*)$", line.strip())
            if m:
                invs.append(m.group(1).strip())
    return invs


def _walk(tokens: list[str]) -> tuple[int, object]:
    node: object = cli
    consumed = 0
    for tok in tokens:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", tok):
            break
        if isinstance(node, click.Group) and tok in node.commands:
            node = node.commands[tok]
            consumed += 1
        else:
            break
    return consumed, node


def test_readme_oracle_commands_are_real():
    invs = _readme_oracle_invocations()
    assert invs, "expected the README to contain oracle command examples"
    for inv in invs:
        tokens = inv.split()
        if tokens and tokens[0].startswith("-"):
            continue  # e.g. `oracle --help`
        consumed, node = _walk(tokens)
        assert consumed >= 1, f"unknown oracle command in README: {inv!r}"
        # A group alone is not a valid invocation; must land on a leaf command.
        assert isinstance(node, click.Command) and not isinstance(node, click.Group), (
            f"README command does not resolve to a leaf subcommand: {inv!r}"
        )
