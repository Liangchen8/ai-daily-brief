from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


def retryable_request(function):
    return retry(
        retry=retry_if_exception_type(RETRYABLE),
        wait=wait_exponential(multiplier=0.4, min=0.4, max=4),
        stop=stop_after_attempt(3),
        reraise=True,
    )(function)

