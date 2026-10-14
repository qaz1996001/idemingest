"""Idempotent sensor-data ingestion.

Replay safety instead of exactly-once delivery: every batch carries a content
fingerprint, so re-running it is a no-op rather than a duplicate.
"""

from idemingest.model import Batch, File, IngestOutcome, IngestResult
from idemingest.errors import CorruptFile, TransientError
from idemingest.store import Store
from idemingest.ingest import Ingestor

__all__ = [
    "Batch",
    "File",
    "IngestOutcome",
    "IngestResult",
    "CorruptFile",
    "TransientError",
    "Store",
    "Ingestor",
]
