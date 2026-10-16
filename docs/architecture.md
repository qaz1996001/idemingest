*English ｜ [繁體中文](architecture.zh-TW.md)*

# Architecture — four views

[`design.md`](design.md) argues *why* replay safety beats exactly-once.
This page shows *what the code actually does*, in four views.

Diagrams are generated from JSON in [`src/`](src); edit the JSON and
re-render rather than hand-editing the SVG.

---

## 1. Control flow

![control flow](flow.svg)

The order of the four steps is the design. Steps 1–2 make a replay free:
the fingerprint is cheap and the dedup check short-circuits before any
I/O, which is why a duplicate reports `attempts == 0`.

Step 3 before step 4 is what keeps a known-bad batch out of the retry
loop. Only step 4 is wrapped in retry, and only `TransientError` reaches
it — a `CorruptFile` is recorded once and never tried again.

Source: [`ingest.py`](../src/idemingest/ingest.py)

## 2. Data flow

![data flow](dataflow.svg)

The fingerprint is computed over `(name, sha256)` pairs **sorted by name**,
so upload order cannot change it. Retries routinely reorder, and without
the sort the same bytes would land twice.

The dedup key is `(device_id, fingerprint)`, not the fingerprint alone.
Two machines can legitimately produce byte-identical readings and both
must be kept.

`snapshot()` exists for the tests: replay-equality is asserted by
comparing two snapshots, so the store needs a deterministic full read.

Source: [`model.py`](../src/idemingest/model.py), [`store.py`](../src/idemingest/store.py)

## 3. Data state

![state transitions](state.svg)

Three outcomes, and the right column is what the tests assert — the row
counts after each one.

The bottom row is the one worth reading twice: a batch that fails midway
leaves `+0` in all three tables. Not a partial batch, not an orphaned
header row. That is what makes the retry safe rather than merely
idempotent-looking.

Source: [`model.py`](../src/idemingest/model.py), [`store.py`](../src/idemingest/store.py)

## 4. Usage scenarios

![scenarios](scenarios.svg)

Six situations the 15 tests cover. Each maps to a named test rather than
being illustrative:

```bash
uv run --with pytest pytest -q -k "replay or corrupt or abort"
```

Source: [`tests/`](../tests)

---

| View | Tests that pin it |
|---|---|
| Control flow | `test_idempotency.py`, `test_failure_classification.py` |
| Data flow | `test_file_order_does_not_change_fingerprint`, `test_same_content_from_two_devices_is_two_batches` |
| Data state | `test_atomicity.py` |
| Scenarios | all three test files |
