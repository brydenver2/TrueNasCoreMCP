"""
HTTP Client implementation with connection pooling, retry logic, and logging
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Union
from functools import wraps
from enum import Enum
import httpx
from httpx import Response, HTTPError, TimeoutException, ConnectError

from ..config import get_settings
from ..exceptions import (
    TrueNASError,
    TrueNASConnectionError,
    TrueNASAuthenticationError,
    TrueNASAPIError,
    TrueNASTimeoutError,
    TrueNASRateLimitError
)


class TrueNASVariant(str, Enum):
    """TrueNAS product variant"""
    CORE = "core"       # TrueNAS Core (FreeBSD-based)
    SCALE = "scale"     # TrueNAS SCALE (Linux-based)
    UNKNOWN = "unknown"

logger = logging.getLogger(__name__)


def retry_on_failure(default_max_retries: int = 3, default_backoff_factor: float = 2.0):
    """Retry failed HTTP calls using instance-level configuration when available."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            settings = getattr(self, "settings", None)
            max_retries = getattr(settings, "http_max_retries", default_max_retries) or default_max_retries
            backoff_factor = getattr(settings, "http_retry_backoff_factor", default_backoff_factor) or default_backoff_factor
            max_retries = max(1, int(max_retries))

            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(self, *args, **kwargs)
                except (TimeoutException, ConnectError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor ** attempt if backoff_factor > 0 else 0
                        logger.warning(
                            f"Request failed (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {wait_time:.2f}s: {str(e)}"
                        )
                        if wait_time:
                            await asyncio.sleep(wait_time)
                        else:
                            await asyncio.sleep(0)
                    else:
                        logger.error(f"Request failed after {max_retries} attempts: {str(e)}")
                except HTTPError as e:
                    if hasattr(e, "response") and e.response and 400 <= e.response.status_code < 500:
                        raise
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor ** attempt if backoff_factor > 0 else 0
                        logger.warning(
                            f"HTTP error (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {wait_time:.2f}s: {str(e)}"
                        )
                        if wait_time:
                            await asyncio.sleep(wait_time)
                        else:
                            await asyncio.sleep(0)

            if isinstance(last_exception, TimeoutException):
                raise TrueNASTimeoutError(f"Request timed out after {max_retries} attempts")
            if isinstance(last_exception, ConnectError):
                raise TrueNASConnectionError(f"Connection failed after {max_retries} attempts")
            raise TrueNASAPIError(f"Request failed after {max_retries} attempts: {str(last_exception)}")

        return wrapper

    return decorator


class TrueNASClient:
    """
    HTTP client for TrueNAS API interactions
    
    Provides connection pooling, retry logic, and proper error handling
    """
    
    def __init__(self, settings=None):
        """
        Initialize the TrueNAS client

        Args:
            settings: Optional Settings instance (uses get_settings() if not provided)
        """
        self.settings = settings or get_settings()
        self._client = None
        self._request_count = 0
        self._error_count = 0
        self._variant: TrueNASVariant = TrueNASVariant.UNKNOWN
        self._version: Optional[str] = None
        self._system_info: Optional[Dict[str, Any]] = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def connect(self):
        """Initialize the HTTP client"""
        if self._client is None or getattr(self._client, "is_closed", False):
            verify_config: Union[bool, str] = bool(self.settings.truenas_verify_ssl)
            ca_bundle = getattr(self.settings, "truenas_ca_bundle", None)
            if ca_bundle:
                verify_config = ca_bundle
                logger.info(f"Using custom CA bundle for TrueNAS client: {ca_bundle}")
            elif not self.settings.truenas_verify_ssl:
                verify_config = False
                logger.warning("SSL verification disabled for TrueNAS client")

            transport = httpx.AsyncHTTPTransport(
                verify=verify_config,
                retries=0,  # We handle retries ourselves
                limits=httpx.Limits(
                    max_connections=self.settings.http_pool_connections,
                    max_keepalive_connections=self.settings.http_pool_maxsize,
                    keepalive_expiry=30.0
                )
            )
            
            self._client = httpx.AsyncClient(
                base_url=self.settings.api_base_url,
                headers=self.settings.headers,
                verify=verify_config,
                timeout=httpx.Timeout(self.settings.http_timeout),
                transport=transport,
                follow_redirects=True
            )
            
            logger.info(f"Connected to TrueNAS at {self.settings.truenas_url}")
    
    async def close(self):
        """Close the HTTP client"""
        if self._client:
            client = self._client
            if not getattr(client, "is_closed", False):
                await client.aclose()
            self._client = None
            logger.info("Disconnected from TrueNAS")
    
    async def ensure_connected(self):
        """Ensure the client is connected"""
        if self._client is None:
            await self.connect()
    
    def _log_request(self, method: str, url: str, **kwargs):
        """Log outgoing request"""
        self._request_count += 1
        logger.debug(f"Request #{self._request_count}: {method} {url}")
        if self.settings.log_level == "DEBUG" and kwargs.get("json"):
            logger.debug(f"Request body: {kwargs['json']}")

    def _get_headers(self) -> Dict[str, str]:
        """Return auth headers for tests and diagnostics."""
        return self.settings.headers.copy()
    
    def _log_response(self, response: Response):
        """Log incoming response"""
        elapsed_seconds = 0.0
        try:
            if hasattr(response, "elapsed") and response.elapsed is not None:
                elapsed_seconds = float(response.elapsed.total_seconds())
        except Exception:
            elapsed_seconds = 0.0

        logger.debug(f"Response: {getattr(response, 'status_code', 'n/a')} ({elapsed_seconds:.2f}s)")
        if self.settings.log_level == "DEBUG" and getattr(response, "content", None):
            try:
                logger.debug(f"Response body: {response.json()}")
            except:
                pass  # Not JSON response
    
    def _handle_error_response(self, response: Response):
        """Handle error responses from the API"""
        status_code = response.status_code
        
        try:
            error_data = response.json()
            error_message = error_data.get("message", response.text)
        except:
            error_message = response.text
        
        self._error_count += 1
        
        if status_code == 401:
            raise TrueNASAuthenticationError(f"Authentication failed: {error_message}")
        elif status_code == 403:
            raise TrueNASAuthenticationError(f"Permission denied: {error_message}")
        elif status_code == 429:
            raise TrueNASRateLimitError(f"Rate limit exceeded: {error_message}")
        elif 400 <= status_code < 500:
            raise TrueNASAPIError(f"Client error ({status_code}): {error_message}")
        elif 500 <= status_code < 600:
            raise TrueNASAPIError(f"Server error ({status_code}): {error_message}")
        else:
            raise TrueNASAPIError(f"Unexpected status ({status_code}): {error_message}")

    @retry_on_failure()
    async def _send_with_retry(self, method: str, endpoint: str, **kwargs) -> Response:
        """Send an HTTP request with retry semantics and error handling."""
        await self.ensure_connected()
        request_kwargs = kwargs.copy()
        self._log_request(method, endpoint, **request_kwargs)
        response = await self._client.request(method, endpoint, **request_kwargs)
        self._log_response(response)

        if response.status_code >= 400:
            self._handle_error_response(response)

        return response

    async def request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Public request helper used by tests and tools."""
        response = await self._send_with_retry(method.upper(), endpoint, **kwargs)

        if response.status_code == 204 or not response.content:
            return {}

        try:
            return response.json()
        except ValueError:
            return {"content": response.text}

    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request("GET", endpoint, params=params)

    async def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request("POST", endpoint, json=data)

    async def put(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request("PUT", endpoint, json=data)

    async def post_raw(
        self,
        endpoint: str,
        data: str,
        content_type: str = "application/json"
    ) -> Dict[str, Any]:
        logger.debug(f"Raw body: {data}")
        response = await self._send_with_retry(
            "POST",
            endpoint,
            content=data.encode(),
            headers={"Content-Type": content_type},
        )
        if not response.content:
            return {}
        return response.json()

    async def delete(self, endpoint: str) -> bool:
        response = await self._send_with_retry("DELETE", endpoint)
        return response.status_code < 300
    
    def get_stats(self) -> Dict[str, int]:
        """Get client statistics"""
        return {
            "requests": self._request_count,
            "errors": self._error_count,
            "error_rate": self._error_count / max(self._request_count, 1)
        }

    @property
    def variant(self) -> TrueNASVariant:
        """Get the detected TrueNAS variant"""
        return self._variant

    @property
    def version(self) -> Optional[str]:
        """Get the TrueNAS version string"""
        return self._version

    @property
    def is_scale(self) -> bool:
        """Check if connected to TrueNAS SCALE"""
        return self._variant == TrueNASVariant.SCALE

    @property
    def is_core(self) -> bool:
        """Check if connected to TrueNAS Core"""
        return self._variant == TrueNASVariant.CORE

    async def detect_variant(self) -> TrueNASVariant:
        """
        Detect the TrueNAS variant (Core vs SCALE) by querying system info

        TrueNAS SCALE returns system info with 'version' containing 'SCALE'
        TrueNAS Core returns system info with 'version' containing 'CORE'

        Returns:
            TrueNASVariant enum value
        """
        await self.ensure_connected()

        try:
            # Query system info
            system_info = await self.get("/system/info")
            self._system_info = system_info

            # Extract version info
            version = system_info.get("version", "")
            self._version = version

            # Detect variant from version string
            version_upper = version.upper()
            if "SCALE" in version_upper:
                self._variant = TrueNASVariant.SCALE
                logger.info(f"Detected TrueNAS SCALE: {version}")
            elif "CORE" in version_upper:
                self._variant = TrueNASVariant.CORE
                logger.info(f"Detected TrueNAS Core: {version}")
            else:
                # Additional detection: SCALE is Linux-based
                # Try querying an endpoint that only exists on SCALE
                try:
                    await self.get("/app")
                    self._variant = TrueNASVariant.SCALE
                    logger.info(f"Detected TrueNAS SCALE (via /app endpoint): {version}")
                except TrueNASAPIError:
                    # /app doesn't exist - likely Core
                    self._variant = TrueNASVariant.CORE
                    logger.info(f"Detected TrueNAS Core (via /app 404): {version}")

        except Exception as e:
            logger.warning(f"Failed to detect TrueNAS variant: {e}")
            self._variant = TrueNASVariant.UNKNOWN

        return self._variant

    def get_system_info(self) -> Optional[Dict[str, Any]]:
        """Get cached system info (call detect_variant first)"""
        return self._system_info


# Global client instance
_client: Optional[TrueNASClient] = None


async def get_client() -> TrueNASClient:
    """
    Get or create the global TrueNAS client instance
    
    Returns:
        TrueNASClient instance
    """
    global _client
    if _client is None:
        _client = TrueNASClient()
        await _client.connect()
    return _client


async def close_client():
    """Close the global client instance"""
    global _client
    if _client:
        await _client.close()
        _client = None