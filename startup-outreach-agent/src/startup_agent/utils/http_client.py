"""HTTP client utility with retries, timeout management, and rate limiting."""

import logging
import time
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger("startup_agent.http")

DEFAULT_USER_AGENT = (
    "StartupJobOutreachAgent/0.1.0 (Personal Job Search Assistant; +https://github.com/personal/startup-outreach-agent)"
)
DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_FACTOR = 1.0


class HttpClient:
    """Configured HTTP client providing resilient requests with backoff."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
        max_retries: int = DEFAULT_RETRIES,
        rate_limit_delay: float = 0.5,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time = 0.0

    def _apply_rate_limit(self) -> None:
        """Enforce delay between consecutive outgoing requests."""
        if self.rate_limit_delay <= 0:
            return
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Execute a GET request with retries and rate limiting.

        Args:
            url: Target URL.
            params: Optional query parameters.
            headers: Optional request headers.

        Returns:
            httpx.Response: Successful HTTP response.

        Raises:
            httpx.HTTPError: If request fails after maximum retry attempts.
        """
        req_headers = {"User-Agent": self.user_agent}
        if headers:
            req_headers.update(headers)

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            self._apply_rate_limit()
            try:
                with httpx.Client(
                    timeout=self.timeout,
                    follow_redirects=True,
                    headers=req_headers,
                ) as client:
                    resp = client.get(url, params=params)
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                        sleep_time = DEFAULT_BACKOFF_FACTOR * (2**attempt)
                        logger.warning(
                            "Transient status %d for %s (attempt %d/%d). Backing off for %.1fs...",
                            resp.status_code,
                            url,
                            attempt + 1,
                            self.max_retries + 1,
                            sleep_time,
                        )
                        time.sleep(sleep_time)
                        continue

                    resp.raise_for_status()
                    return resp
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    sleep_time = DEFAULT_BACKOFF_FACTOR * (2**attempt)
                    logger.warning(
                        "Network error '%s' on %s (attempt %d/%d). Retrying in %.1fs...",
                        exc,
                        url,
                        attempt + 1,
                        self.max_retries + 1,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error("Request failed after %d retries: %s", self.max_retries, exc)
                    raise
            except httpx.HTTPStatusError as exc:
                logger.error("HTTP status error %s for %s", exc.response.status_code, url)
                raise

        if last_exception:
            raise last_exception
        raise httpx.HTTPError(f"Request to {url} failed without explicit response.")

    def post(
        self,
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Execute a POST request with retries and rate limiting."""
        req_headers = {"User-Agent": self.user_agent}
        if headers:
            req_headers.update(headers)

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            self._apply_rate_limit()
            try:
                with httpx.Client(
                    timeout=self.timeout,
                    follow_redirects=True,
                    headers=req_headers,
                ) as client:
                    resp = client.post(url, json=json_data)
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                        sleep_time = DEFAULT_BACKOFF_FACTOR * (2**attempt)
                        logger.warning(
                            "Transient status %d for %s (attempt %d/%d). Backing off for %.1fs...",
                            resp.status_code,
                            url,
                            attempt + 1,
                            self.max_retries + 1,
                            sleep_time,
                        )
                        time.sleep(sleep_time)
                        continue

                    resp.raise_for_status()
                    return resp
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    sleep_time = DEFAULT_BACKOFF_FACTOR * (2**attempt)
                    time.sleep(sleep_time)
                else:
                    raise
            except httpx.HTTPStatusError as exc:
                logger.error("HTTP status error %s for %s", exc.response.status_code, url)
                raise

        if last_exception:
            raise last_exception
        raise httpx.HTTPError(f"POST request to {url} failed.")

