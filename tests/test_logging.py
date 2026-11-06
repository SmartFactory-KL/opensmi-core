# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

import io
import json
import logging
import logging.handlers
from collections.abc import Iterator

import pytest
import structlog

from opensmi.core import console_formatter, json_formatter, setup_logging
from opensmi.core import logging as core_logging


@pytest.fixture
def captured() -> Iterator[tuple[logging.Logger, logging.StreamHandler[io.StringIO]]]:
    """A logger of its own with a handler writing to a string; structlog's defaults restored afterwards."""
    logger = logging.getLogger("opensmi.test_logging")
    handler = logging.StreamHandler(io.StringIO())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    yield logger, handler
    logger.removeHandler(handler)
    structlog.reset_defaults()


def _failing() -> None:
    msg = "bad value"
    raise ValueError(msg)


def test_plain_stdlib_record_rendered_like_structlog(captured) -> None:
    logger, handler = captured
    handler.setFormatter(console_formatter(colors=False))
    logger.warning("read %s failed", "Foo")
    line = handler.stream.getvalue()
    assert "[warning  ]" in line
    assert "read Foo failed" in line
    assert "[opensmi.test_logging]" in line
    assert "\x1b[" not in line


def test_structlog_key_values(captured) -> None:
    _, handler = captured
    structlog.configure(  # as setup_logging with KEY_VALUE
        processors=[*core_logging._shared_processors(), structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    handler.setFormatter(console_formatter(colors=False))
    structlog.get_logger("opensmi.test_logging").info("connected", machine="Storage")
    line = handler.stream.getvalue()
    assert "[info     ]" in line
    assert "connected" in line
    assert "machine=Storage" in line


def test_colors(captured) -> None:
    logger, handler = captured
    handler.setFormatter(console_formatter())
    logger.warning("colored")
    assert "\x1b[" in handler.stream.getvalue()


def test_full_traceback_by_default(captured) -> None:
    logger, handler = captured
    handler.setFormatter(console_formatter(colors=False))
    try:
        _failing()
    except ValueError:
        logger.exception("read failed")
    output = handler.stream.getvalue()
    assert "_failing" in output  # a frame of the traceback
    assert "bad value" in output


def test_tracebacks_off_keeps_only_the_last_line(captured) -> None:
    logger, handler = captured
    handler.setFormatter(console_formatter(colors=False, tracebacks=False))
    try:
        _failing()
    except ValueError:
        logger.exception("read failed")
    output = handler.stream.getvalue()
    assert output.count("\n") == 1  # one line
    assert output.rstrip().endswith("[opensmi.test_logging] ValueError: bad value")
    assert "_failing" not in output


def test_full_traceback_without_colors_has_no_locals(captured) -> None:
    logger, handler = captured
    handler.setFormatter(console_formatter(colors=False))
    secret = "hunter" + "2"  # not in the source lines the traceback shows
    try:
        _failing()
    except ValueError:
        logger.exception("login failed for %s", len(secret))
    assert repr(secret) not in handler.stream.getvalue()  # as the locals would show it


@pytest.fixture
def fresh_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[logging.Logger]:
    """setup_logging as in a new process: logging not yet set up; tests force out pytest's root handlers."""
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    monkeypatch.setattr(core_logging, "_logging_initialized", False)
    for name in ("FORMAT", "LEVEL", "CONSOLE", "FILE", "FILE_LEVEL", "FILE_MAX_BYTES", "FILE_BACKUPS"):
        monkeypatch.delenv(f"LOG_{name}", raising=False)
    yield root
    for handler in root.handlers:
        handler.close()
    root.handlers[:], level = saved
    root.setLevel(level)
    structlog.reset_defaults()


def test_log_file_only_with_its_level_and_rotation(fresh_root, tmp_path) -> None:
    path = tmp_path / "app.log"
    setup_logging(
        log_format=core_logging.LogFormat.KEY_VALUE,
        console=False,
        log_file=path,
        log_file_level="ERROR",
        log_file_max_bytes=300,
        log_file_backups=1,
        force_basic_config=True,
    )
    assert not any(type(h) is logging.StreamHandler for h in fresh_root.handlers)  # no console
    assert not path.exists()  # created on the first record
    log = structlog.get_logger("opensmi.app")
    log.warning("not in the file")
    for i in range(5):
        log.error("in the file", i=i)
    for handler in fresh_root.handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "not in the file" not in text
    assert "i=4" in text
    assert "\x1b[" not in text
    assert (tmp_path / "app.log.1").exists()
    assert not (tmp_path / "app.log.2").exists()


def test_json_to_file_includes_plain_stdlib_records(fresh_root, tmp_path) -> None:
    path = tmp_path / "app.jsonl"
    setup_logging(log_format=core_logging.LogFormat.JSON, console=False, log_file=path, force_basic_config=True)
    structlog.get_logger("opensmi.app").info("structured", n=1)
    logging.getLogger("opensmi.plain").warning("plain %s", "record")
    for handler in fresh_root.handlers:
        handler.flush()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["event"] == "structured"
    assert records[0]["n"] == 1
    assert records[1]["event"] == "plain record"
    assert records[1]["level"] == "warning"


def test_environment_overrides_arguments(fresh_root, tmp_path, monkeypatch) -> None:
    path = tmp_path / "env.log"
    monkeypatch.setenv("LOG_CONSOLE", "0")
    monkeypatch.setenv("LOG_FILE", str(path))
    monkeypatch.setenv("LOG_FILE_LEVEL", "warning")
    monkeypatch.setenv("LOG_FORMAT", "json")
    setup_logging(log_format=core_logging.LogFormat.KEY_VALUE, console=True, force_basic_config=True)
    assert [type(h) for h in fresh_root.handlers] == [logging.handlers.RotatingFileHandler]
    log = logging.getLogger("opensmi.env")
    log.info("below the file level")
    log.warning("in the file")
    for handler in fresh_root.handlers:
        handler.flush()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["event"] for r in records] == ["in the file"]


def test_invalid_environment_values_are_ignored_and_logged(fresh_root, tmp_path, monkeypatch) -> None:
    path = tmp_path / "app.log"
    monkeypatch.setenv("LOG_FILE_LEVEL", "LOUD")
    monkeypatch.setenv("LOG_FILE_MAX_BYTES", "abc")
    setup_logging(
        log_format=core_logging.LogFormat.KEY_VALUE,
        console=False,
        log_file=path,
        log_file_level="WARNING",
        force_basic_config=True,
    )
    (handler,) = fresh_root.handlers
    assert handler.level == logging.WARNING  # the argument
    assert handler.maxBytes == 0
    handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "Invalid environment variable LOG_FILE_LEVEL='LOUD' ignored" in text
    assert "Invalid environment variable LOG_FILE_MAX_BYTES='abc' ignored" in text


def test_json_formatter_for_own_handlers(captured) -> None:
    logger, handler = captured
    handler.setFormatter(json_formatter())
    logger.warning("plain %s", "record")
    record = json.loads(handler.stream.getvalue())
    assert record["event"] == "plain record"
    assert record["logger"] == "opensmi.test_logging"
