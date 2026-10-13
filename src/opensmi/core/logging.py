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
from pathlib import PurePath
from typing import Any, Final

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


def _path_to_str(_, __, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:  # noqa: ANN001
    """Convert ``path`` entry in structlog processor event dict to simple string."""
    if "path" in event_dict:
        path = event_dict["path"]
        if isinstance(path, PurePath):
            event_dict["path"] = str(path)
    return event_dict


_logging_initialized = False
"""Global flag indicated whether logging is initialized."""


class LogFormat(Enum):
    """Structured logging format to use."""

    AUTOMATIC = "automatic"
    """Automatic logging output, KEY_VALUE if there is a terminal, otherwise JSON."""
    KEY_VALUE = "key_value"
    """Key=Value formatted logging output"""
    JSON = "json"
    """JSON formatted logging output"""


def _setup_key_value_logging(
    *,
    min_level: int | str = logging.NOTSET,
    enable_rich_tracebacks: bool = True,
) -> None:
    from importlib.util import find_spec

    # see https://www.structlog.org/en/stable/logging-best-practices.html#pretty-printing-vs-structured-output
    if find_spec("rich") is not None and enable_rich_tracebacks:
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
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _elapsed_to_ms,
        _path_to_str,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.UnicodeDecoder(),
        console_renderer,
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(min_level=min_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _setup_json_logging(
    *,
    min_level: int | str = logging.NOTSET,
) -> None:

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _path_to_str,
        structlog.processors.dict_tracebacks,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    try:
        import orjson

        _LOGGER.info("Using orjson serialization")

        processors.append(structlog.processors.JSONRenderer(serializer=orjson.dumps))
        logger_factory = structlog.BytesLoggerFactory()
    except ImportError:
        _LOGGER.warning("Could not import orjson, fallback to builtin serializer.")

        processors.append(structlog.processors.JSONRenderer())
        logger_factory = structlog.stdlib.LoggerFactory()

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(min_level=min_level),
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )


DEFAULT_LOG_LEVELS: Final[dict[str, int | str]] = {
    "opensmi": logging.INFO,
    "asyncua": logging.ERROR,
}


def setup_logging(
    *,
    log_min_level: int | str = logging.NOTSET,
    log_levels: Mapping[str, int | str] | None = None,
    log_format: LogFormat = LogFormat.AUTOMATIC,
    enable_rich_tracebacks: bool = True,
    force_basic_config: bool = False,
) -> None:
    """Set up structured logging.

    ``log_format`` can be overridden with the ``LOG_FORMAT`` environment variable.

    :param log_min_level: Minimum logging level for structlog loggers.
    :param log_levels: Logging levels for *all* loggers. Maps logger name to level. Defaults to `DEFAULT_LOG_LEVELS`.
    :param log_format: Logging format for *all* loggers.
    :param enable_rich_tracebacks: Enable Rich tracebacks if `KEY_VALUE` log format is used.
    :param force_basic_config: ``force`` parameter of ``logging.basicConfig``.
    """
    global _logging_initialized
    if _logging_initialized:
        return

    logging.basicConfig(format="", force=force_basic_config)

    if log_levels is None:
        log_levels = DEFAULT_LOG_LEVELS

    # structlog loggers created via structlog.stdlib.LoggerFactory are also gated by the stdlib level
    if log_min_level != logging.NOTSET and (log_levels is None or "" not in log_levels):
        logging.getLogger().setLevel(log_min_level)

    if log_levels is not None:
        for name, level in log_levels.items():
            try:
                logging.getLogger(name).setLevel(level)
                _LOGGER.debug("Set logger level of %r to %s", name, level)
            except (TypeError, ValueError):
                _LOGGER.exception("Could not set logger level of %r to %s", name, level)
    if _LOGGER.level == logging.NOTSET:
        _LOGGER.setLevel(logging.INFO)

    # override given log_format from environment
    env_log_format = os.getenv("LOG_FORMAT", None)
    if env_log_format is not None:
        try:
            log_format = LogFormat[env_log_format.upper()]
        except KeyError:
            _LOGGER.warning("Invalid log format %r", env_log_format)

    if log_format == LogFormat.AUTOMATIC:
        if sys.stderr.isatty():
            _LOGGER.info("Automatic logging with attached terminal.")
            log_format = LogFormat.KEY_VALUE
        else:
            _LOGGER.info("Automatic logging without attached terminal.")
            log_format = LogFormat.JSON

    if log_format == LogFormat.KEY_VALUE:
        _setup_key_value_logging(min_level=log_min_level, enable_rich_tracebacks=enable_rich_tracebacks)
    else:  # JSON
        _setup_json_logging(min_level=log_min_level)

    _logging_initialized = True
