"""contracts.safe_logging: loglarga token va bot sirlari tushmasligi."""

import io
import logging

from contracts import safe_logging
from contracts.safe_logging import RedactFilter, redact

BOT = "bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw0"
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.sig-part_abc"


def test_redacts_bot_token_in_telegram_url():
    text = f"HTTP Request: POST https://api.telegram.org/{BOT}/sendMessage \"HTTP/1.1 200 OK\""
    out = redact(text)
    assert "AAHdq" not in out and "123456789" not in out
    assert "https://api.telegram.org/bot***/sendMessage" in out


def test_redacts_query_tokens_and_signatures():
    assert redact(f"WebSocket /api/drivers/ws/dispatch?token={JWT} [accepted]").endswith("?token=*** [accepted]")
    assert redact("GET /x?a=1&access_token=abc&refresh_token=def") == "GET /x?a=1&access_token=***&refresh_token=***"
    assert redact("/support/files/5?exp=1&sig=deadbeef") == "/support/files/5?exp=1&sig=***"


def test_leaves_normal_text_alone():
    for text in ("order token_count=5 ok", "bot started", "robot123456789:short", "tokenizer=on"):
        assert redact(text) == text


def _logger_with_handler(fmt="%(message)s"):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(RedactFilter())
    log = logging.getLogger(f"safe-test-{id(stream)}")
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(handler)
    return log, stream


def test_filter_redacts_message_and_args():
    log, stream = _logger_with_handler()
    log.info("%s - \"WebSocket %s\" [accepted]", "1.2.3.4:5", f"/ws?token={JWT}")
    log.info(f"POST https://api.telegram.org/{BOT}/sendMessage")
    out = stream.getvalue()
    assert JWT not in out and "AAHdq" not in out
    assert "/ws?token=***" in out and "bot***" in out


def test_filter_keeps_uvicorn_access_args_shape():
    """uvicorn AccessFormatter 5 ta argumentni kutadi — filtr ularni buzmasligi kerak."""
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("1.2.3.4:5", "GET", f"/files/1?sig=abc", "1.1", 200), None,
    )
    assert RedactFilter().filter(record) is True
    assert isinstance(record.args, tuple) and len(record.args) == 5
    assert record.args[2] == "/files/1?sig=***" and record.args[4] == 200


def test_install_silences_httpx_and_is_idempotent():
    handler = logging.StreamHandler(io.StringIO())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        safe_logging.install()
        safe_logging.install()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
        assert sum(isinstance(f, RedactFilter) for f in handler.filters) == 1
    finally:
        root.removeHandler(handler)
