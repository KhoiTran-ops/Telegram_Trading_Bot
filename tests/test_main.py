from unittest.mock import AsyncMock

import pytest
from telegram.error import TimedOut

from main import _initialize_with_retry


@pytest.mark.asyncio
async def test_initialize_retries_after_temporary_telegram_timeout() -> None:
    application = AsyncMock()
    application.initialize.side_effect = [TimedOut("temporary"), None]
    sleep = AsyncMock()

    await _initialize_with_retry(application, delay_seconds=0, sleep=sleep)

    assert application.initialize.await_count == 2
    sleep.assert_awaited_once_with(0)
