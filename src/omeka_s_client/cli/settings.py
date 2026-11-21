"""Configuration for the command line."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..client import OmekaClient
from ..transport import Transport


class OmekaSettings(BaseSettings):
    """Read Omeka configuration from the environment or an explicit file.

    >>> OmekaSettings(url="https://example.org", timeout=12).timeout
    12.0
    """

    model_config = SettingsConfigDict(
        env_prefix="OMEKA_", extra="ignore", hide_input_in_errors=True
    )

    url: str = ""
    key_identity: SecretStr | None = None
    key_credential: SecretStr | None = None
    timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)

    def open_client(self, *, transport: Transport | None = None) -> OmekaClient:
        """Open a client with the selected settings."""
        return OmekaClient(
            self.url,
            key_identity=None
            if self.key_identity is None
            else self.key_identity.get_secret_value(),
            key_credential=None
            if self.key_credential is None
            else self.key_credential.get_secret_value(),
            timeout=self.timeout,
            transport=transport,
        )
