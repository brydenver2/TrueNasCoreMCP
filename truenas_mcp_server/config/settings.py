"""
Settings configuration using Pydantic for validation
"""

import os
from functools import lru_cache
from typing import Optional, Dict, Any
from enum import Enum
from pydantic import Field, field_validator, HttpUrl
from pydantic_settings import BaseSettings
from pydantic.types import SecretStr


class LogLevel(str, Enum):
    """Logging level enumeration"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Environment(str, Enum):
    """Application environment"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """
    Application settings with validation
    
    Settings are loaded from environment variables with TRUENAS_ prefix
    """
    
    # TrueNAS Connection Settings  
    truenas_url: HttpUrl = Field(
        default="https://truenas.local",
        description="TrueNAS server URL",
        validation_alias="TRUENAS_URL"
    )
    
    truenas_api_key: SecretStr = Field(
        ...,
        description="TrueNAS API key for authentication",
        validation_alias="TRUENAS_API_KEY"
    )
    
    truenas_verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates",
        validation_alias="TRUENAS_VERIFY_SSL"
    )
    truenas_ca_bundle: Optional[str] = Field(
        default=None,
        description="Path to custom CA bundle (PEM)",
        validation_alias="TRUENAS_CA_BUNDLE"
    )
    
    # Application Settings
    environment: Environment = Field(
        default=Environment.PRODUCTION,
        description="Application environment",
        validation_alias="TRUENAS_ENV"
    )
    
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Logging level",
        validation_alias="TRUENAS_LOG_LEVEL"
    )
    
    # HTTP Client Settings
    http_timeout: float = Field(
        default=60.0,
        description="HTTP request timeout in seconds"
    )
    
    http_max_retries: int = Field(
        default=3,
        description="Maximum number of HTTP retries"
    )

    http_retry_backoff_factor: float = Field(
        default=2.0,
        description="Exponential backoff factor between retries"
    )
    
    http_pool_connections: int = Field(
        default=10,
        description="Number of connection pool connections"
    )
    
    http_pool_maxsize: int = Field(
        default=20,
        description="Maximum size of the connection pool"
    )
    
    # Feature Flags & Cache
    enable_debug_tools: bool = Field(
        default=False,
        description="Enable debug tools in production",
    )

    enable_destructive_operations: bool = Field(
        default=False,
        description="Enable potentially destructive operations",
    )

    enable_cache: bool = Field(
        default=True,
        description="Enable in-memory caching layer",
    )

    enable_metrics: bool = Field(
        default=False,
        description="Enable Prometheus-style metrics collection",
    )

    cache_ttl: int = Field(
        default=300,
        description="Cache time-to-live in seconds",
    )

    cache_max_size: int = Field(
        default=1000,
        description="Maximum cache entries",
    )

    # Rate Limiting
    rate_limit_enabled: bool = Field(
        default=False,
        description="Enable rate limiting",
    )

    rate_limit_per_minute: int = Field(
        default=60,
        description="Allowed requests per minute",
    )

    rate_limit_burst: int = Field(
        default=10,
        description="Allowed burst size",
    )
    
    @field_validator("truenas_url", mode="before")
    def validate_url(cls, v):
        """Ensure URL doesn't end with slash"""
        if isinstance(v, str):
            return v.rstrip("/")
        return v

    @field_validator("truenas_verify_ssl", mode="before")
    def normalize_verify_ssl(cls, value):
        """Support string env values like 'false' or '0'."""
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"0", "false", "off", "no"}:
                return False
            if lowered in {"1", "true", "on", "yes"}:
                return True
        return value

    @field_validator("truenas_ca_bundle", mode="before")
    def normalize_ca_bundle(cls, value):
        """Normalize CA bundle paths and ignore blank strings."""
        if not value:
            return None
        path = os.path.expanduser(str(value).strip())
        return path if path else None
    
    @field_validator("environment")
    def validate_debug_tools(cls, v):
        """Auto-enable debug tools in development"""
        # Note: In Pydantic v2, we can't modify other fields in validators
        # This logic should be in a model_validator or handled differently
        return v
    
    @property
    def api_base_url(self) -> str:
        """Get the full API base URL"""
        base = str(self.truenas_url).rstrip("/")
        return f"{base}/api/v2.0"
    
    @property
    def headers(self) -> Dict[str, str]:
        """Get HTTP headers for API requests"""
        return {
            "Authorization": f"Bearer {self.truenas_api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "User-Agent": f"TrueNAS-MCP-Server/{self.get_version()}"
        }
    
    def get_version(self) -> str:
        """Get the package version"""
        from .. import __version__
        return __version__
    
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.environment == Environment.PRODUCTION
    
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.environment == Environment.DEVELOPMENT
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
        "use_enum_values": False,
        "populate_by_name": True
    }


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance
    
    Returns a singleton Settings instance that's cached for the application lifetime
    """
    return Settings()


def reload_settings() -> Settings:
    """
    Force reload settings (useful for testing)
    
    Clears the cache and returns a new Settings instance
    """
    get_settings.cache_clear()
    return get_settings()