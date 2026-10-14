"""The property the whole design exists for: replay changes nothing."""

from idemingest import IngestOutcome
from tests.conftest import make_batch


def test_same_batch_twice_leaves_store_identical(ingestor, store):
    batch = make_batch()

    first = ingestor.ingest(batch)
    after_first = store.snapshot()

    second = ingestor.ingest(batch)
    after_second = store.snapshot()

    assert first.outcome is IngestOutcome.STORED
    assert second.outcome is IngestOutcome.DUPLICATE
    assert after_first == after_second, "replay must not change stored state"


def test_replaying_ten_times_is_still_one_batch(ingestor, store):
    batch = make_batch()
    results = ingestor.replay([batch] * 10)

    assert results[0].outcome is IngestOutcome.STORED
    assert all(r.outcome is IngestOutcome.DUPLICATE for r in results[1:])
    assert store.counts()["batches"] == 1
    assert store.counts()["files"] == 3


def test_duplicate_does_no_work(ingestor):
    batch = make_batch()
    ingestor.ingest(batch)
    second = ingestor.ingest(batch)
    # attempts == 0 proves the write path was never entered.
    assert second.attempts == 0
    assert second.ok


def test_file_order_does_not_change_fingerprint():
    a = make_batch()
    b = a.__class__(
        device_id=a.device_id, files=tuple(reversed(a.files)), captured_at=a.captured_at
    )
    assert a.fingerprint == b.fingerprint


def test_different_content_is_a_different_batch(ingestor, store):
    ingestor.ingest(make_batch())
    ingestor.ingest(make_batch(salt=b"different"))
    assert store.counts()["batches"] == 2


def test_same_content_from_two_devices_is_two_batches(ingestor, store):
    """The key is (device, content) -- two machines can legitimately
    produce byte-identical readings and both must be kept."""
    ingestor.ingest(make_batch(device_id="dev-001"))
    ingestor.ingest(make_batch(device_id="dev-002"))
    assert store.counts()["batches"] == 2
