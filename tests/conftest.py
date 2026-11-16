from collections.abc import Iterator
import logging

import pytest

from ldgrep import ldgrep


@pytest.fixture(autouse=True)
def restore_ldgrep_logging() -> Iterator[None]:
    """Restore ldgrep logger configuration after each test."""
    logger = logging.getLogger("ldgrep")
    original_handlers = tuple(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    original_configured_handler = ldgrep._logging_handler

    yield

    for handler in tuple(logger.handlers):
        if handler not in original_handlers:
            logger.removeHandler(handler)
            handler.close()
    for handler in original_handlers:
        if handler not in logger.handlers:
            logger.addHandler(handler)

    logger.setLevel(original_level)
    logger.propagate = original_propagate
    ldgrep._logging_handler = original_configured_handler
