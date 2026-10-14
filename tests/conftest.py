import pytest

from idemingest import Batch, File, Ingestor, Store


@pytest.fixture
def store():
    s = Store()
    yield s
    s.close()


@pytest.fixture
def ingestor(store):
    return Ingestor(store)


def make_batch(device_id="dev-001", n=3, captured_at="2026-10-15T09:00:00Z", salt=b""):
    files = tuple(
        File(name=f"A{i:03d}.csv", payload=b"ts,x,y,z\n1,0.1,0.2,0.3\n" + salt)
        for i in range(1, n + 1)
    )
    return Batch(device_id=device_id, files=files, captured_at=captured_at)
