"""Deterministic failures must not be retried; transient ones must be."""

import pytest

from idemingest import Batch, File, IngestOutcome, Ingestor, Store
from idemingest.errors import CorruptFile, TransientError
from tests.conftest import make_batch


def test_corrupt_batch_is_marked_failed(ingestor, store):
    bad = Batch(device_id="dev-001", files=(File("A001.csv", b""),))
    result = ingestor.ingest(bad)

    assert result.outcome is IngestOutcome.FAILED
    assert not result.ok
    assert store.counts()["batches"] == 0
    assert store.failure_reason(*bad.key) is not None


def test_corrupt_batch_is_tried_exactly_once(store):
    """A poison message retried forever is how an ingest queue dies."""
    calls = []

    def counting_validator(batch):
        calls.append(batch.fingerprint)
        raise CorruptFile("always bad")

    ing = Ingestor(store, validators=(counting_validator,), max_attempts=5)
    ing.ingest(make_batch())

    assert len(calls) == 1, "deterministic failure must not be retried"


def test_transient_failure_is_retried_then_succeeds(store, monkeypatch):
    ing = Ingestor(store, max_attempts=3)
    real_write = store.write_batch
    attempts = {"n": 0}

    def flaky(batch):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TransientError("database busy")
        return real_write(batch)

    monkeypatch.setattr(store, "write_batch", flaky)
    result = ing.ingest(make_batch())

    assert result.outcome is IngestOutcome.STORED
    assert result.attempts == 3
    assert store.counts()["batches"] == 1


def test_transient_failure_gives_up_at_the_bound(store, monkeypatch):
    ing = Ingestor(store, max_attempts=3)
    monkeypatch.setattr(
        store, "write_batch", lambda b: (_ for _ in ()).throw(TransientError("down"))
    )
    result = ing.ingest(make_batch())

    assert result.outcome is IngestOutcome.FAILED
    assert result.attempts == 3
    assert "after 3 attempts" in result.reason


def test_a_failed_batch_can_be_replayed_successfully(store, monkeypatch):
    """Recovery story: the outage ends, you replay, it lands exactly once."""
    ing = Ingestor(store, max_attempts=2)
    batch = make_batch()

    monkeypatch.setattr(
        store, "write_batch", lambda b: (_ for _ in ()).throw(TransientError("down"))
    )
    assert ing.ingest(batch).outcome is IngestOutcome.FAILED

    monkeypatch.undo()
    assert ing.ingest(batch).outcome is IngestOutcome.STORED
    assert ing.ingest(batch).outcome is IngestOutcome.DUPLICATE
    assert store.counts()["batches"] == 1


def test_max_attempts_must_be_positive(store):
    with pytest.raises(ValueError):
        Ingestor(store, max_attempts=0)
