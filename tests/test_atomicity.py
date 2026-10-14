"""A partial write must leave nothing behind, or replay is not safe.

The failure is injected with a SQLite trigger rather than a mock, so the
abort happens inside the real transaction the real code opened.
"""

import sqlite3

import pytest

from idemingest import Ingestor
from tests.conftest import make_batch

_POISON = "A003.csv"

_TRIGGER = f"""
CREATE TRIGGER fail_on_poison
BEFORE INSERT ON files
WHEN NEW.name = '{_POISON}'
BEGIN
    SELECT RAISE(ABORT, 'simulated disk I/O error');
END;
"""


def test_abort_midway_through_a_batch_writes_nothing(store):
    """Batch row and the first two files are already inserted when the
    third one aborts. If the transaction boundary is wrong, they survive."""
    batch = make_batch(n=4)
    assert any(f.name == _POISON for f in batch.files)

    store._conn.executescript(_TRIGGER)
    ing = Ingestor(store, max_attempts=1)

    with pytest.raises(sqlite3.IntegrityError):
        ing.ingest(batch)

    counts = store.counts()
    assert counts["batches"] == 0, "batch row survived a failed transaction"
    assert counts["files"] == 0, "file rows survived a failed transaction"


def test_after_an_abort_the_batch_can_be_ingested_cleanly(store):
    """Nothing was recorded, so the retry is an ordinary first ingest."""
    batch = make_batch(n=4)
    store._conn.executescript(_TRIGGER)
    ing = Ingestor(store, max_attempts=1)

    with pytest.raises(sqlite3.IntegrityError):
        ing.ingest(batch)

    store._conn.executescript("DROP TRIGGER fail_on_poison;")
    result = ing.ingest(batch)

    assert result.ok
    assert store.counts()["batches"] == 1
    assert store.counts()["files"] == 4


def test_every_stored_batch_has_all_its_files(ingestor, store):
    for i in range(5):
        ingestor.ingest(make_batch(device_id=f"dev-{i:03d}", n=4))

    rows = store.snapshot()
    declared = {(d, f): n for d, f, _, n in rows["batches"]}
    actual: dict = {}
    for device_id, fingerprint, *_ in rows["files"]:
        actual[(device_id, fingerprint)] = actual.get((device_id, fingerprint), 0) + 1

    assert declared == actual
