"""Logging configuration utility."""

import logging
from pathlib import Path
from typing import Optional


def setup_logging(
    log_level: str = "INFO",
    logs_dir: Optional[Path] = None,
) -> logging.Logger:
    """Configure console and file logging.

    Args:
        log_level: Desired log level string (DEBUG, INFO, WARNING, ERROR).
        logs_dir: Optional directory path where logs will be saved.

    Returns:
        logging.Logger: Configured application logger instance.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    if logs_dir is None:
        logs_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs"

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = logs_dir / "app.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    return logging.getLogger("startup_agent")

