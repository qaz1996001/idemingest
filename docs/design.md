*English ｜ [繁體中文](design.zh-TW.md)*

# Design notes

Two diagrams for the two decisions the README argues for.

---

## 1. The dedup key, and why recovery is not a separate path

A batch is fingerprinted before anything else happens. If that fingerprint has
been seen for that device, the whole write path is skipped — no I/O, no
transaction, `attempts == 0`.

`replay()` does not have its own logic. It re-enters this same flow, which is
why the recovery path cannot rot: it is the path that runs every day.

```mermaid
flowchart TD
    A["batch arrives"] --> B["fingerprint<br/>sha256 of sorted name+digest pairs"]
    B --> C{"already stored?<br/>key = device_id + fingerprint"}
    C -->|yes| D["DUPLICATE<br/>attempts = 0, nothing touched"]
    C -->|no| E{"validate"}
    E -->|CorruptFile| F["FAILED<br/>recorded, never retried"]
    E -->|passes| G["write batch + files<br/>in ONE transaction"]
    G -->|TransientError| H{"attempts < max?"}
    H -->|yes| G
    H -->|no| I["FAILED<br/>reason recorded"]
    G -->|commit| J["STORED"]
    R(["replay()"]) -.->|same entry point,<br/>no separate logic| A

    style D fill:#e8f0fe,stroke:#1f4e79
    style J fill:#e6f4ea,stroke:#1e7e34
    style F fill:#fce8e6,stroke:#a50e0e
    style I fill:#fce8e6,stroke:#a50e0e
```

Two details the diagram encodes:

- **The fingerprint sorts files by name before hashing**, so upload order cannot
  change it. Retries routinely reorder.
- **The key is `(device, content)`, not content alone.** Two machines can
  legitimately produce byte-identical readings, and both must be kept.

---

## 2. Why deterministic failures are never retried

Retrying a failure that cannot succeed is how an ingestion queue dies. The
poison message comes back forever and starves everything behind it.

```mermaid
flowchart TB
    subgraph bad["Retry everything"]
        direction TB
        A1["corrupt batch"] --> A2["retry"]
        A2 --> A3["same bytes,<br/>same failure"]
        A3 --> A2
        A4["batch 2"] -.-> A5["starved —<br/>never reached"]
        A6["batch 3"] -.-> A5
    end

    subgraph good["Split the taxonomy"]
        direction TB
        B1["corrupt batch"] --> B2["validated once"]
        B2 --> B3["FAILED,<br/>leaves the queue"]
        B4["batch 2"] --> B5["processed"]
        B6["batch 3"] --> B5
    end

    style A5 fill:#fce8e6,stroke:#a50e0e
    style B3 fill:#e8f0fe,stroke:#1f4e79
    style B5 fill:#e6f4ea,stroke:#1e7e34
```

The taxonomy has exactly two members on purpose:

| | Can retrying change the outcome? | Action |
|---|---|---|
| `CorruptFile` | No — the bytes are the bytes | Record and stop. One attempt. |
| `TransientError` | Yes — the world was busy | Retry to a bound |

*Which* parser failed, or *which* socket timed out, is detail for the log. It is
not an input to the retry decision, so it does not get its own exception class.

Validation runs **before** the write, so a known-bad batch never enters the
retry loop in the first place. That ordering is the whole mechanism.

---

## Where the tests sit against this

| Diagram element | Test |
|---|---|
| `DUPLICATE` with `attempts = 0` | `test_duplicate_does_no_work` |
| Fingerprint ignores file order | `test_file_order_does_not_change_fingerprint` |
| Key is `(device, content)` | `test_same_content_from_two_devices_is_two_batches` |
| `CorruptFile` tried exactly once | `test_corrupt_batch_is_tried_exactly_once` |
| `TransientError` retries, then succeeds | `test_transient_failure_is_retried_then_succeeds` |
| One transaction, all-or-nothing | `test_abort_midway_through_a_batch_writes_nothing` |
| `replay()` re-enters the same flow | `test_a_failed_batch_can_be_replayed_successfully` |
