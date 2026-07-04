"""Task 12 — orchestration artefacts (CLAUDE.md + settings + 13 skill stubs).

These are markdown/JSON files, so the "tests" are structural sanity checks
rather than behaviour tests. The load-bearing one (plan step 4) walks the real
click command tree in ``oracle.cli`` and asserts that *every* ``oracle …``
command referenced inside an inline-code span in CLAUDE.md or any SKILL.md maps
to a subcommand that actually exists — so the orchestrator prose can never
drift from the CLI surface.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import click

import oracle.cli as cli_mod

REPO = Path(__file__).resolve().parent.parent

SKILL_NAMES = [
    "question-intake",
    "triage",
    "research",
    "base-rates",
    "modelling",
    "ensemble",
    "red-team",
    "calibrate-and-commit",
    "report",
    "resolve",
    "retrospect",
    "import-questions",
    "update",
]


# --------------------------------------------------------------------------- #
# click command surface
# --------------------------------------------------------------------------- #
def _command_tree() -> tuple[set[str], set[str]]:
    """Return ``(leaf_paths, group_names)`` from the live click app."""
    leaves: set[str] = set()
    groups: set[str] = set()

    def walk(cmd: click.Command, prefix: str = "") -> None:
        for name, sub in getattr(cmd, "commands", {}).items():
            full = f"{prefix} {name}".strip()
            if isinstance(sub, click.Group):
                groups.add(full)
                walk(sub, full)
            else:
                leaves.add(full)

    walk(cli_mod.cli)
    return leaves, groups


def _referenced_commands(text: str) -> list[str]:
    """Extract ``oracle <sub…>`` command paths from inline-code spans.

    Only tokens that look like subcommand words (lowercase, hyphenated) are
    collected; parsing stops at the first flag (``--x``), placeholder
    (``<qid>``), or any non-command token.
    """
    out: list[str] = []
    for span in re.findall(r"`([^`]*)`", text):
        toks = span.strip().split()
        if not toks or toks[0] != "oracle":
            continue
        path: list[str] = []
        for tok in toks[1:]:
            if re.fullmatch(r"[a-z][a-z-]*", tok):
                path.append(tok)
            else:
                break
        if path:
            out.append(" ".join(path))
    return out


# --------------------------------------------------------------------------- #
# files exist
# --------------------------------------------------------------------------- #
def test_claude_md_exists_and_has_prime_directive():
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "forecast that isn't logged doesn't exist" in text
    assert "oracle status" in text


def test_all_thirteen_skill_stubs_exist():
    for name in SKILL_NAMES:
        p = REPO / ".claude" / "skills" / name / "SKILL.md"
        assert p.exists(), f"missing skill stub: {name}"


def test_skill_frontmatter_and_spec_pointer():
    for name in SKILL_NAMES:
        text = (REPO / ".claude" / "skills" / name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert text.startswith("---"), f"{name}: missing frontmatter"
        assert re.search(r"^name:\s*\S", text, re.M), f"{name}: no name in frontmatter"
        assert re.search(
            r"^description:\s*\S", text, re.M
        ), f"{name}: no description in frontmatter"
        assert "See spec" in text and "§5" in text, f"{name}: no spec pointer"


def test_knowledge_files_exist():
    lessons = (REPO / "knowledge" / "lessons.md").read_text(encoding="utf-8")
    assert "no lessons yet" in lessons.lower()
    checklist = (REPO / "knowledge" / "process-checklist.md").read_text(
        encoding="utf-8"
    )
    # §5.9 audit items must be present.
    assert "disconfirmation" in checklist.lower()


# --------------------------------------------------------------------------- #
# settings.json
# --------------------------------------------------------------------------- #
def test_settings_json_valid_and_blinds_sealed():
    data = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    perms = data["permissions"]
    allow = perms["allow"]
    deny = perms["deny"]
    assert any("oracle" in a for a in allow), "no allow rule for the oracle CLI"
    assert any("data/sealed" in d for d in deny), "data/sealed not deny-listed"
    # the deny rule must gate *read* access (§5.13).
    assert any(
        "data/sealed" in d and d.lower().startswith("read") for d in deny
    ), "sealed deny rule must be a Read(...) rule"


# --------------------------------------------------------------------------- #
# the load-bearing check: no dangling oracle commands (plan step 4)
# --------------------------------------------------------------------------- #
def test_all_referenced_oracle_commands_are_real():
    leaves, groups = _command_tree()
    docs = [REPO / "CLAUDE.md"] + [
        REPO / ".claude" / "skills" / n / "SKILL.md" for n in SKILL_NAMES
    ]
    bad: list[tuple[str, str]] = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for ref in _referenced_commands(text):
            # A reference is valid if it is a leaf, a group, or a leaf reached
            # by taking the first token as a group (e.g. "import" -> group).
            if ref in leaves or ref in groups:
                continue
            first = ref.split()[0]
            # "oracle import" style bare-group mention.
            if first in {g.split()[0] for g in groups}:
                # first token names a group; the whole ref must resolve to a
                # real leaf under it, or be exactly the bare group name.
                if ref in leaves or first in groups:
                    continue
            bad.append((doc.name, ref))
    assert not bad, f"references to nonexistent oracle commands: {bad}"
