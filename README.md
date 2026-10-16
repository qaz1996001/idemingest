*English ｜ [繁體中文](README.zh-TW.md)*

# idemingest — replay safety instead of exactly-once delivery

A minimal, runnable demonstration of one design decision: **when sensor data
has to land in more than one place and the link can drop mid-write, make every
batch safe to re-run instead of trying to make it succeed exactly once.**

```bash
uv run --with pytest pytest -q      # 15 passed
```

No external services. No broker, no server, no network. `pytest` is the only
dependency.

Four views of what the code does -- control flow, data flow, state transitions
and usage scenarios -- are in [docs/architecture.md](docs/architecture.md).

---

## The problem

An industrial gateway uploads a measurement session — several sensor files
captured at the same moment. The server has to write them to two stores that
share no transaction manager. The upload link is cellular and drops.

So you get duplicates. The gateway retried, or the operator replayed a day of
backlog, or an upstream worker crashed after writing one store but not the
other. The naive fix is a distributed transaction. The cheaper fix is to make
duplicates harmless.

## The decision

**Deduplicate on `(device_id, content_fingerprint)`, and make the recovery path
the same code as the normal path.**

> Diagram: [docs/design.md § 1](docs/design.md#1-the-dedup-key-and-why-recovery-is-not-a-separate-path)

| | Two-phase commit | Idempotent replay |
|---|---|---|
| Needs a coordinator | yes | no |
| Behaviour when a participant dies mid-commit | blocks, needs recovery protocol | nothing was written; re-run |
| Cost of being wrong | stuck transactions, manual intervention | one wasted re-run |
| Code paths to keep correct | normal + recovery | **one** |

The last row is the real argument. A recovery path that runs twice a year is a
recovery path nobody notices has rotted. Here `replay()` is a loop over
`ingest()` — the recovery path *is* the path that runs every day.

### Why the fingerprint covers the batch, not the file

A per-record upload has no natural unit to deduplicate on: records are small,
numerous, and individually indistinguishable from the next reading. Bundling a
capture session into one unit gives you something meaningful to hash. The
fingerprint sorts files by name before hashing, so **upload order cannot change
it** — which matters, because retries routinely reorder.

### Why failures are split in two

```
CorruptFile    → deterministic. Retrying re-reads the same bytes.
                 Marked failed, tried exactly once.
TransientError → the bytes were fine, the world was busy.
                 Retried to a bound.
```

Retrying a deterministic failure is how an ingestion queue dies: the poison
message comes back forever and starves everything behind it. The taxonomy has
exactly two members on purpose — *which* parser failed is detail for the log,
not an input to the retry decision.

> Diagram: [docs/design.md § 2](docs/design.md#2-why-deterministic-failures-are-never-retried)

### Order of operations

```
1. fingerprint the batch   cheap, no I/O
2. already stored?         → DUPLICATE, touch nothing
3. validate                → deterministic failures die here, unretried
4. write atomically        → transient failures retry around this step only
```

Steps 1–2 make a replay free (`attempts == 0`, asserted in the tests). Step 3
before step 4 keeps a known-bad batch out of the retry loop.

---

## What the tests prove

The tests are the deliverable; the implementation is small on purpose.

**Idempotency** (`test_idempotency.py`)
- Running the same batch twice leaves a **byte-identical store snapshot**
- Ten replays produce one batch row and zero extra file rows
- A duplicate performs no work at all (`attempts == 0`)
- Reordering the files does not change the fingerprint
- Two devices emitting byte-identical readings are kept as two batches —
  the key is `(device, content)`, not content alone

**Failure classification** (`test_failure_classification.py`)
- A corrupt batch is validated **exactly once** even with `max_attempts=5`
- A transient failure retries and succeeds on attempt 3
- A permanent outage gives up at the bound and records why
- **The recovery story end to end**: outage → `FAILED`; outage ends → replay →
  `STORED`; replay again → `DUPLICATE`; final state is one batch

**Atomicity** (`test_atomicity.py`)
- Failure is injected with a SQLite `RAISE(ABORT)` trigger, so the abort happens
  inside the real transaction the real code opened — not around a mock
- After an abort mid-batch: **zero batch rows, zero file rows**
- After the fault clears, the same batch ingests cleanly as a first ingest
- Invariant check: every stored batch's declared `file_count` equals its actual
  number of file rows

---

## Limitations

Stated because a demo that hides its edges is not useful.

- **Single process, single writer.** Concurrent ingest of the same batch is
  handled by `INSERT OR IGNORE` losing harmlessly, but the pre-check and the
  write are not atomic with respect to each other — under real concurrency the
  loser reports `STORED` rather than `DUPLICATE`. The stored state is still
  correct; only the reported outcome is.
- **Payloads are not stored**, only name, size and digest. Real object storage
  is the interesting half of the problem and is out of scope here.
- **SHA-256 over the whole payload** is fine at this scale and wrong at high
  throughput; production would hash while streaming to disk rather than holding
  the payload in memory.
- **No broker.** MQTT/AMQP delivery semantics are what create the duplicates
  this handles, but adding a broker would make the tests need infrastructure,
  which would make them stop being run.
- **Retry has no backoff.** A real client needs exponential backoff and jitter;
  omitted so the retry assertions stay deterministic.

---

## Where this came from

This is a from-scratch reimplementation of a design decision I made on an
industrial IoT platform, where sensor data had to land in two stores with no
distributed transaction available and the uplink was unreliable.
**No code from that system is used here** — the repository was written from
nothing for this demonstration. What carries over is the reasoning, which is
in [docs/design.md](docs/design.md).

MIT licensed.
