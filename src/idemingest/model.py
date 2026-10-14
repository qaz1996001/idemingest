"""Value objects.

A ``Batch`` is one measurement session: everything a device captured at one
moment, uploaded together. Bundling is what makes the fingerprint meaningful
-- a per-record upload has no natural unit to deduplicate on.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class File:
    """One file inside a batch."""

    name: str
    payload: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(frozen=True)
class Batch:
    """One measurement session from one device."""

    device_id: str
    files: tuple[File, ...]
    captured_at: str = ""

    @property
    def fingerprint(self) -> str:
        """Content hash of the whole batch.

        Built from each file's name and sha256, sorted by name so that upload
        order cannot change the fingerprint. Two uploads of the same bytes
        produce the same fingerprint even if the files arrive in a different
        order -- which is the whole point, because retries routinely do.
        """
        h = hashlib.sha256()
        for f in sorted(self.files, key=lambda f: f.name):
            h.update(f.name.encode())
            h.update(b"\0")
            h.update(f.sha256.encode())
            h.update(b"\0")
        return h.hexdigest()

    @property
    def key(self) -> tuple[str, str]:
        """The deduplication key: (device, content)."""
        return (self.device_id, self.fingerprint)


class IngestOutcome(str, Enum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True)
class IngestResult:
    outcome: IngestOutcome
    device_id: str
    fingerprint: str
    attempts: int = 1
    reason: str = ""
    files_written: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Duplicate counts as success: the data is in the store."""
        return self.outcome in (IngestOutcome.STORED, IngestOutcome.DUPLICATE)
