# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Common structured logging utilities."""

import logging
import logging.handlers
import os
import shutil
import sys
import traceback
from collections.abc import Callable, Mapping, MutableMapping
from enum import Enum
from pathlib import PurePath
from typing import Any, Final, TextIO

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


def _exception_line(sio: TextIO, exc_info: Any) -> None:
    """Render an exception as its last traceback line ``ExcType: message`` only, after the log line."""
    sio.write(" " + traceback.format_exception_only(exc_info[1])[-1].strip())


def _shared_processors(*, utc: bool = False) -> list[Any]:
    """Processors for structlog and foreign (plain stdlib) records alike, before rendering."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _elapsed_to_ms,
        _path_to_str,
        structlog.processors.TimeStamper(fmt="iso", utc=utc),
        structlog.processors.UnicodeDecoder(),
    ]


def _console_formatter(*, colors: bool, tracebacks: bool, rich_tracebacks: bool) -> logging.Formatter:
    from importlib.util import find_spec

    if not tracebacks:
        exception_formatter: Any = _exception_line
    elif find_spec("rich") is not None and rich_tracebacks:
        exception_formatter = structlog.dev.RichTracebackFormatter(
            color_system="truecolor" if colors else None,
            show_locals=colors,  # a terminal only: files and other outputs could keep secrets from locals
            width=shutil.get_terminal_size(fallback=(160, 24)).columns,
        )
    else:
        exception_formatter = structlog.dev.plain_traceback
    renderer = structlog.dev.ConsoleRenderer(sort_keys=False, colors=colors, exception_formatter=exception_formatter)
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )


def console_formatter(*, colors: bool = True, tracebacks: bool = True) -> logging.Formatter:
    """Formatter rendering structlog and plain stdlib records as Key=Value lines, like ``LogFormat.KEY_VALUE``.

    For handlers of applications with their own logging setup, after `setup_logging` with ``LogFormat.KEY_VALUE``.

    :param colors: ANSI colors in the output; also the local variables in Rich tracebacks.
    :param tracebacks: Full tracebacks (Rich if installed); otherwise only their last line ``ExcType: message``.
    """
    return _console_formatter(colors=colors, tracebacks=tracebacks, rich_tracebacks=True)


def json_formatter() -> logging.Formatter:
    """Formatter rendering structlog and plain stdlib records as JSON lines, like ``LogFormat.JSON``.

    For handlers of applications with their own logging setup, after `setup_logging` with ``LogFormat.JSON``.
    """
    try:
        import orjson

        renderer = structlog.processors.JSONRenderer(serializer=lambda obj, **kw: orjson.dumps(obj, **kw).decode())
    except ImportError:
        renderer = structlog.processors.JSONRenderer()
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(utc=True),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.dict_tracebacks,
            renderer,
        ],
    )


def _file_handler(
    log_file: str | os.PathLike[str], *, level: int | str, max_bytes: int, backups: int
) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8", delay=True
    )
    handler.setLevel(level)
    return handler


def _from_env(name: str, value: Any, convert: Callable[[str], Any], invalid: list[str]) -> Any:
    """Return the environment variable ``name`` converted; ``value`` if it's unset or invalid."""
    raw = os.getenv(name)
    if raw is None:
        return value
    try:
        return convert(raw)
    except (KeyError, ValueError):
        invalid.append(f"{name}={raw!r}")
        return value


def _level(raw: str) -> int:
    if raw.strip().isdigit():
        return int(raw)
    level = logging.getLevelNamesMapping().get(raw.strip().upper())
    if level is None:
        raise ValueError(raw)
    return level


def _flag(raw: str) -> bool:
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError(raw)


def _resolve_format(log_format: LogFormat) -> LogFormat:
    """AUTOMATIC: KEY_VALUE on a terminal, else JSON."""
    # see https://www.structlog.org/en/stable/logging-best-practices.html#pretty-printing-vs-structured-output
    if log_format == LogFormat.AUTOMATIC:
        if sys.stderr.isatty():
            _LOGGER.info("Automatic logging with attached terminal.")
            return LogFormat.KEY_VALUE
        _LOGGER.info("Automatic logging without attached terminal.")
        return LogFormat.JSON
    return log_format


def _set_levels(log_min_level: int | str, log_levels: Mapping[str, int | str]) -> None:
    # structlog loggers created via structlog.stdlib.LoggerFactory are also gated by the stdlib level
    if log_min_level != logging.NOTSET and "" not in log_levels:
        logging.getLogger().setLevel(log_min_level)
    for name, level in log_levels.items():
        try:
            logging.getLogger(name).setLevel(level)
            _LOGGER.debug("Set logger level of %r to %s", name, level)
        except (TypeError, ValueError):
            _LOGGER.exception("Could not set logger level of %r to %s", name, level)
    if _LOGGER.level == logging.NOTSET:
        _LOGGER.setLevel(logging.INFO)


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
    console: bool = True,
    log_file: str | os.PathLike[str] | None = None,
    log_file_level: int | str = logging.NOTSET,
    log_file_max_bytes: int = 0,
    log_file_backups: int = 0,
) -> None:
    """Set up structured logging.

    Environment variables override the arguments: ``LOG_FORMAT`` (``key_value``, ``json``, ``automatic``),
    ``LOG_LEVEL`` (``log_min_level``), ``LOG_CONSOLE`` (``1`` / ``0``), ``LOG_FILE`` (empty: none),
    ``LOG_FILE_LEVEL``, ``LOG_FILE_MAX_BYTES`` and ``LOG_FILE_BACKUPS``. Invalid values are logged and ignored.

    If the root logger already has handlers (and ``force_basic_config`` is false), none are added: those handlers
    need `console_formatter` to render structlog records.

    :param log_min_level: Minimum logging level for structlog loggers.
    :param log_levels: Logging levels for *all* loggers. Maps logger name to level. Defaults to `DEFAULT_LOG_LEVELS`.
    :param log_format: Logging format for *all* loggers, on the console and in the log file.
    :param enable_rich_tracebacks: Enable Rich tracebacks if `KEY_VALUE` log format is used.
    :param force_basic_config: ``force`` parameter of ``logging.basicConfig``.
    :param console: Log to stderr.
    :param log_file: Also log to this file: appended, UTF-8, created on the first record, no colors.
    :param log_file_level: Minimum level of the records written to ``log_file``.
    :param log_file_max_bytes: Rotate ``log_file`` at this size; 0: never.
    :param log_file_backups: Number of rotated files kept (``.1``, ``.2``, ...).
    """
    global _logging_initialized
    if _logging_initialized:
        return

    invalid: list[str] = []
    log_format = _from_env("LOG_FORMAT", log_format, lambda raw: LogFormat[raw.strip().upper()], invalid)
    log_min_level = _from_env("LOG_LEVEL", log_min_level, _level, invalid)
    console = _from_env("LOG_CONSOLE", console, _flag, invalid)
    log_file = _from_env("LOG_FILE", log_file, lambda raw: raw or None, invalid)
    log_file_level = _from_env("LOG_FILE_LEVEL", log_file_level, _level, invalid)
    log_file_max_bytes = _from_env("LOG_FILE_MAX_BYTES", log_file_max_bytes, int, invalid)
    log_file_backups = _from_env("LOG_FILE_BACKUPS", log_file_backups, int, invalid)

    console_handler = logging.StreamHandler() if console else None
    file_handler = None
    if log_file is not None:
        file_handler = _file_handler(
            log_file, level=log_file_level, max_bytes=log_file_max_bytes, backups=log_file_backups
        )
    ours = [h for h in (console_handler, file_handler) if h is not None] or [logging.NullHandler()]
    logging.basicConfig(handlers=ours, format="", force=force_basic_config)
    if not set(ours) <= set(logging.getLogger().handlers):  # the root already had handlers: the application's own
        console_handler = file_handler = None

    _set_levels(log_min_level, DEFAULT_LOG_LEVELS if log_levels is None else log_levels)

    log_format = _resolve_format(log_format)
    rich = enable_rich_tracebacks
    if log_format == LogFormat.KEY_VALUE:
        if console_handler is not None:
            console_handler.setFormatter(_console_formatter(colors=True, tracebacks=True, rich_tracebacks=rich))
        if file_handler is not None:
            file_handler.setFormatter(_console_formatter(colors=False, tracebacks=True, rich_tracebacks=rich))
    else:  # JSON
        for handler in (console_handler, file_handler):
            if handler is not None:
                handler.setFormatter(json_formatter())

    structlog.configure(
        processors=[
            *_shared_processors(utc=log_format == LogFormat.JSON),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(min_level=log_min_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _logging_initialized = True
    for setting in invalid:
        _LOGGER.warning("Invalid environment variable %s ignored", setting)
