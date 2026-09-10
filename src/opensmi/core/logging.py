# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Common structured logging utilities."""

import logging
import os
import shutil
import sys
from collections.abc import Mapping, MutableMapping
from enum import Enum
from typing import Any

import structlog

_LOGGER = logging.getLogger(__name__)


def _format_elapsed(seconds: float) -> str:
    """Format given ``seconds`` into short human-readable string."""
    if seconds >= 1:
        return f"{seconds:.3f}s"
    return f"{seconds * 1000:.1f}ms"


def _elapsed_to_ms(_, __, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:  # noqa: ANN001
    """Convert ``elapsed`` entry in structlog processor event dict to shorter format."""
    if "elapsed" in event_dict:
        event_dict["elapsed"] = _format_elapsed(event_dict["elapsed"])
    return event_dict


_logging_initialized = False
""" Global flag indicated whether logging is initialized. """


class LogFormat(Enum):
    """Structured logging format to use."""

    AUTOMATIC = "automatic"
    """Automatic logging output, KEY_VALUE if there is a terminal, otherwise JSON."""
    KEY_VALUE = "key_value"
    """Key=Value formatted logging output"""
    JSON = "json"
    """JSON formatted logging output"""


def _setup_console_logging() -> None:
    from importlib.util import find_spec

    # see https://www.structlog.org/en/stable/logging-best-practices.html#pretty-printing-vs-structured-output
    if find_spec("rich") is not None:
        console_renderer = structlog.dev.ConsoleRenderer(
            sort_keys=False,
            exception_formatter=structlog.dev.RichTracebackFormatter(
                width=shutil.get_terminal_size(fallback=(160, 24)).columns
            ),
        )
    else:
        console_renderer = structlog.dev.ConsoleRenderer(sort_keys=False)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _elapsed_to_ms,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.UnicodeDecoder(),
        console_renderer,
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _setup_key_value_logging() -> None:
    try:
        import orjson

        _LOGGER.info("Using orjson serialization")
        processors = [
            structlog.contextvars.merge_contextvars,
            # structlog.stdlib.filter_by_level,
            # structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            _elapsed_to_ms,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(serializer=orjson.dumps),
        ]
        logger_factory = structlog.BytesLoggerFactory()
    except ImportError:
        _LOGGER.warning("Could not import orjson, fallback to buildin serializer.")

        processors = [
            structlog.contextvars.merge_contextvars,
            # structlog.stdlib.filter_by_level,
            # structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            _elapsed_to_ms,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
        logger_factory = structlog.stdlib.LoggerFactory()

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )


def setup_logging(
    *,
    log_levels: Mapping[str, int | str] | None = None,
    log_format: LogFormat = LogFormat.AUTOMATIC,
) -> None:
    """Set up structured logging."""
    global _logging_initialized
    if _logging_initialized:
        return

    logging.basicConfig(force=True, format="")
    if log_levels is not None:
        for name, level in log_levels.items():
            try:
                logging.getLogger(name).setLevel(level)
                _LOGGER.debug(f"Set logger level of '{name}' to {level}")
            except (TypeError, ValueError):
                _LOGGER.exception(f"Could not set logger level of '{name}' to {level}")
    if _LOGGER.level == logging.NOTSET:
        _LOGGER.setLevel(logging.INFO)

    # override given log_format from environment
    env_log_format = os.getenv("LOG_FORMAT", None)
    if env_log_format is not None:
        try:
            log_format = LogFormat[env_log_format.upper()]
        except ValueError:
            _LOGGER.warning(f"Invalid log format '{env_log_format}'")

    if log_format == LogFormat.AUTOMATIC:
        if sys.stderr.isatty():
            _LOGGER.info("Automatic logging with attached terminal.")
            log_format = LogFormat.KEY_VALUE
        else:
            _LOGGER.info("Automatic logging without attached terminal.")
            log_format = LogFormat.JSON

    if log_format == LogFormat.KEY_VALUE:
        _setup_console_logging()
    else:  # JSON
        _setup_key_value_logging()

    _logging_initialized = True
