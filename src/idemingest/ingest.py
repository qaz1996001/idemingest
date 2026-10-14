"""The ingest path.

Order of operations is the design:

1. fingerprint the batch   -- cheap, no I/O
2. already stored?         -- return DUPLICATE, touch nothing
3. validate                -- deterministic failures die here, unretried
4. write atomically        -- transient failures retry around this step only

Steps 1 and 2 are what make a replay free. Step 3 before step 4 is what
keeps a known-bad batch out of the retry loop.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from idemingest.errors import CorruptFile, TransientError
from idemingest.model import Batch, IngestOutcome, IngestResult
from idemingest.store import Store

_log = logging.getLogger("idemingest")

Validator = Callable[[Batch], None]


def reject_empty_files(batch: Batch) -> None:
    """Example validator: an empty file is always wrong, never a blip."""
    for f in batch.files:
        if not f.payload:
            raise CorruptFile(f"empty file: {f.name}")


class Ingestor:
    """Ingest batches so that running the same batch twice is a no-op.

    Parameters
    ----------
    store:
        Where batches land.
    validators:
        Run before any write. Raise :class:`CorruptFile` to reject
        permanently; anything else propagates.
    max_attempts:
        Upper bound on retries for :class:`TransientError` only.
    """

    def __init__(
        self,
        store: Store,
        validators: Iterable[Validator] = (reject_empty_files,),
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._store = store
        self._validators = tuple(validators)
        self._max_attempts = max_attempts

    def ingest(self, batch: Batch) -> IngestResult:
        device_id, fingerprint = batch.key

        # 2. Seen before? Nothing to do. This is the replay fast path.
        if self._store.has_batch(device_id, fingerprint):
            return IngestResult(
                IngestOutcome.DUPLICATE, device_id, fingerprint, attempts=0
            )

        # 3. Deterministic validation. Failing here is terminal.
        try:
            for validate in self._validators:
                validate(batch)
        except CorruptFile as exc:
            self._store.record_failure(device_id, fingerprint, str(exc))
            _log.warning("rejected device=%s reason=%s", device_id, exc)
            return IngestResult(
                IngestOutcome.FAILED, device_id, fingerprint, attempts=1, reason=str(exc)
            )

        # 4. Write, retrying only what retrying can fix.
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                written = self._store.write_batch(batch)
            except TransientError as exc:
                last = exc
                _log.info("transient failure attempt=%d device=%s", attempt, device_id)
                continue
            return IngestResult(
                IngestOutcome.STORED,
                device_id,
                fingerprint,
                attempts=attempt,
                files_written=written,
            )

        reason = f"transient failure after {self._max_attempts} attempts: {last}"
        self._store.record_failure(device_id, fingerprint, reason)
        return IngestResult(
            IngestOutcome.FAILED,
            device_id,
            fingerprint,
            attempts=self._max_attempts,
            reason=reason,
        )

    def replay(self, batches: Iterable[Batch]) -> list[IngestResult]:
        """Re-run a sequence of batches.

        There is no separate replay logic -- replay is just ingest again.
        That is the property worth having: the recovery path is the path
        that runs every day, so it cannot rot unnoticed.
        """
        return [self.ingest(b) for b in batches]
