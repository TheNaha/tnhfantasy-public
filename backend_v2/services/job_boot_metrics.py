"""Stamp job.metadata_['boot_seconds'] at the first provider-originated event.

"Boot time" is how long a dispatch took to get its FIRST streaming event back
from the provider: for Modal/Beam that is the cold container boot (the number
the user is buying), for remote workers it is handshake + agent round trip,
for direct APIs it is near zero. The symmetry matters: the provider page's
"boot" column must mean the same stage of the same trip for every transport.

``started_at`` is stamped when the job first entered an active state, so
``now - started_at`` measured at the first provider event covers exactly the
dispatch→first-own-event leg — queueing time excluded, wall-clock boot
included for serverless.

The stamp happens ONCE per job: the first write wins and later frames are
re-stamp-guarded both in memory (bounded set, so progress-heavy LLM jobs don't
re-read the row every frame) and in the metadata itself (so a restart cannot
double-stamp either). Mutable-column gotcha honored: metadata is rebuilt into
a NEW dict and reassigned via ``update_job(metadata_=...)`` — an in-place
mutation of the existing dict would not persist.
"""

from datetime import datetime, timezone

from core.exceptions import NotFoundError
from services.job_service import as_utc
from infrastructure.logging import get_logger

logger = get_logger("job_boot_metrics")

# Process-local re-stamp guard. Bounded: a long-lived backend accumulating
# job ids is a (tiny) leak until the cap, at which point the whole set is
# dropped — the metadata contents are the durable half of the guard, so a
# cleared set can only ever cause an extra no-op check per job.
_boot_stamped: set[str] = set()
_BOOT_STAMPED_SET_LIMIT = 4096


def _remember(job_id: str) -> None:
    if len(_boot_stamped) >= _BOOT_STAMPED_SET_LIMIT:
        _boot_stamped.clear()
    _boot_stamped.add(job_id)


async def stamp_boot_seconds(job_service, job_id: str | None) -> None:
    """Stamp ``metadata_['boot_seconds']`` once, on the first provider event.

    Callers: the in-process reducers in ``services/provider_client`` (which
    receive every TaskEvent the engine streams) and the external-worker
    socket handlers in ``api/routes/worker_ws``. Together those two seams see
    the first provider-originated frame of every transport.

    Best-effort by design: no boot measurement — whatsoever — is allowed to
    break or delay the job whose boot it is measuring.
    """
    if not job_id or job_id in _boot_stamped:
        return

    try:
        job = await job_service.get_job(job_id)
    except NotFoundError:
        # Gone between the event and the stamp. Forget the guard entry so a
        # legitimately reused id is not blocked; nothing to stamp anyway.
        _boot_stamped.discard(job_id)
        return
    except Exception as exc:
        logger.debug("boot_stamp_lookup_failed", job_id=job_id, error=str(exc))
        return

    started_at = job.started_at
    if started_at is None:
        # Not activated yet — there is no interval to measure. The job stays
        # stampable so a LATER frame (after started_at exists) can measure it.
        return

    # From here a stamp decision exists, so remember the job: no later frame
    # re-reads the row.
    _remember(job_id)

    existing = job.metadata_ if isinstance(job.metadata_, dict) else {}
    if existing.get("boot_seconds") is not None:
        return

    started_at = as_utc(started_at)
    boot_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
    metadata = dict(existing)
    metadata["boot_seconds"] = round(boot_seconds, 1)
    try:
        await job_service.update_job(job_id, metadata_=metadata)
    except Exception as exc:
        logger.debug("boot_stamp_write_failed", job_id=job_id, error=str(exc))
