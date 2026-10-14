"""Failure taxonomy.

The only distinction that matters at ingest time is whether retrying can
change the outcome.  Everything else (which parser failed, which socket
timed out) is detail for the log, not for the retry decision.
"""


class IngestError(Exception):
    """Base class. Never raised directly."""


class CorruptFile(IngestError):
    """Deterministic failure: the bytes are wrong.

    Retrying re-reads the same bytes and fails the same way, so the batch is
    marked failed and never retried. Retrying these is how a queue ends up
    replaying a poison message forever.
    """


class TransientError(IngestError):
    """Non-deterministic failure: the bytes are fine, the world was busy.

    Network blips, lock contention, a database that was restarting. Retrying
    can succeed, so it is retried up to a bounded number of attempts.
    """
