"""Tenacity retry decorator for all external API calls."""

from __future__ import annotations

import logging

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# Standard retry decorator for all external API calls
# 3 attempts, 2s initial wait, doubling each time (2s, 4s, 8s max)
api_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    retry=retry_if_exception_type((
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.HTTPError,
    )),
    reraise=True,
)
