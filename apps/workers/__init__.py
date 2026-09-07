"""Worker package — claim queued upload jobs and run ingest pipeline."""

from shared.db import get_session_factory, init_db
from shared.logging import configure_logging, get_logger

from workers.pipeline import claim_queued_jobs, process_upload_job

configure_logging()
logger = get_logger("worker")


def main() -> None:
    init_db()
    session_factory = get_session_factory()
    with session_factory() as db:
        job_ids = claim_queued_jobs(db, limit=20)
        if not job_ids:
            logger.info("worker_idle", message="no queued jobs")
            print("workers: no queued jobs")
            return
        for job_id in job_ids:
            try:
                result = process_upload_job(db, job_id)
                db.commit()
                logger.info("worker_job_done", **result.__dict__)
                print(f"indexed job={result.job_id} chunks={result.chunk_count}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.exception("worker_job_error", job_id=job_id, error=str(exc))
                print(f"failed job={job_id}: {exc}")


if __name__ == "__main__":
    main()
