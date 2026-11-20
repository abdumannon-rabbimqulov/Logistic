"""Telegram Mini App initData timestamp validation regression tests."""
import hashlib
import hmac
import json
from time import time
from urllib.parse import urlencode

import pytest

from users.telegram_auth import validate_telegram_init_data


BOT_TOKEN = "123456:test-token"


def signed_data(auth_date):
    fields = {"user": json.dumps({"id": 123}), "auth_date": str(auth_date)}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_timestamp():
    assert validate_telegram_init_data(signed_data(int(time())), BOT_TOKEN)["id"] == 123


@pytest.mark.parametrize("timestamp", ["", "invalid", "0", "-1", str(int(time()) + 3600)])
def test_invalid_timestamps_are_rejected(timestamp):
    with pytest.raises(ValueError, match="auth_date"):
        validate_telegram_init_data(signed_data(timestamp), BOT_TOKEN)


def test_expired_timestamp():
    with pytest.raises(ValueError, match="muddati"):
        validate_telegram_init_data(signed_data(int(time()) - 90000), BOT_TOKEN)
