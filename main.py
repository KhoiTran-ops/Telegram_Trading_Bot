"""Local long-polling entry point for the Telegram bot."""

import logging

from telegram import Update

from bot.application import create_application
from common.config import Settings
from common.logging_config import configure_logging


logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    settings = Settings()
    application = create_application(settings)
    logger.info(
        "telegram bot starting",
        extra={"event": "bot_starting", "entry_point": "long_polling"},
    )
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
