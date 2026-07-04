"""Append-only forecast/resolution store (§6.1, §7.4).

The ledger is git-tracked JSON on disk: one file per record, named by the
record id. Records are never mutated — corrections are new ``ForecastRecord``s
that reference the prior point via ``supersedes`` (§6.1). ``append_*`` therefore
refuses to overwrite an existing file.

Two namespaces exist (§7.4): ``live`` writes under ``data/ledger/`` and drives
the headline scoreboard; ``backtest`` writes under ``data/ledger/backtest/`` and
is quarantined from live numbers. Backtest records must never be mixed into live
scoring, so the two namespaces resolve to disjoint directories and neither scans
into the other.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from oracle.models import ForecastRecord, ResolutionRecord

_RESOLUTION_SUFFIX = ".resolution.json"


class Ledger:
    """On-disk append-only store for forecasts and resolutions.

    Parameters
    ----------
    root:
        The Oracle state root (the directory that contains ``data/``).
    namespace:
        ``"live"`` (default) or ``"backtest"`` (§7.4).
    """

    def __init__(self, root: Path, namespace: str = "live") -> None:
        if namespace not in ("live", "backtest"):
            raise ValueError(
                f"namespace must be 'live' or 'backtest', got {namespace!r}"
            )
        self.root = Path(root)
        self.namespace = namespace
        base = self.root / "data" / "ledger"
        self.dir = base if namespace == "live" else base / "backtest"
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- writes ---------------------------------------------------------------

    def append_forecast(self, rec: ForecastRecord) -> Path:
        """Write ``data/ledger[/backtest]/<id>.json``; refuse to overwrite."""
        path = self.dir / f"{rec.id}.json"
        self._write_new(path, rec.model_dump_json(indent=2))
        return path

    def append_resolution(self, rec: ResolutionRecord) -> Path:
        """Write the resolution for a forecast; refuse to overwrite."""
        path = self.dir / f"{rec.forecast_id}{_RESOLUTION_SUFFIX}"
        self._write_new(path, rec.model_dump_json(indent=2))
        return path

    @staticmethod
    def _write_new(path: Path, payload: str) -> None:
        # Exclusive create: raises FileExistsError if the record already exists,
        # enforcing the append-only invariant without a check-then-write race.
        with open(path, "x", encoding="utf-8") as fh:
            fh.write(payload)

    # -- reads ----------------------------------------------------------------

    def get_forecast(self, fid: str) -> ForecastRecord:
        path = self.dir / f"{fid}.json"
        if not path.exists():
            raise FileNotFoundError(f"no forecast {fid!r} in {self.dir}")
        return ForecastRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def resolution_for(self, fid: str) -> ResolutionRecord | None:
        path = self.dir / f"{fid}{_RESOLUTION_SUFFIX}"
        if not path.exists():
            return None
        return ResolutionRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def all_forecasts(self) -> list[ForecastRecord]:
        """Every forecast in this namespace (does not descend into subdirs)."""
        out: list[ForecastRecord] = []
        for path in self._forecast_files():
            out.append(
                ForecastRecord.model_validate_json(path.read_text(encoding="utf-8"))
            )
        return out

    def stream(self, question_id: str) -> list[ForecastRecord]:
        """All forecasts for a question, ordered by ``stream_seq``."""
        matches = [r for r in self.all_forecasts() if r.question_id == question_id]
        return sorted(matches, key=lambda r: r.stream_seq)

    def next_seq(self, prefix: str, date: datetime) -> int:
        """Next 1-based sequence for ``<prefix>-<YYYYMMDD>-NNN`` on ``date``.

        Scans existing record filenames in this namespace and returns
        ``max(seq) + 1`` for the given date, or ``1`` if none exist.
        """
        stem = f"{prefix}-{date:%Y%m%d}-"
        max_seq = 0
        for path in self._forecast_files():
            name = path.stem  # filename without .json
            if not name.startswith(stem):
                continue
            tail = name[len(stem):]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
        return max_seq + 1

    # -- internals ------------------------------------------------------------

    def _forecast_files(self) -> list[Path]:
        # Only direct children (no rglob) so the live namespace never picks up
        # the nested backtest directory. Resolution sidecars are excluded.
        return [
            p
            for p in self.dir.glob("*.json")
            if not p.name.endswith(_RESOLUTION_SUFFIX)
        ]
