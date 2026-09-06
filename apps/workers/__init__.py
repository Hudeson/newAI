"""Worker package (E0 stub)."""

from shared.logging import configure_logging, get_logger

configure_logging()
logger = get_logger("worker")


def main() -> None:
    logger.info("worker_stub_started", milestone="E0")
    print("workers E0 stub: no consumers yet (starts in E3)")


if __name__ == "__main__":
    main()
