"""Choose the configured ``BankProvider``."""

from finance_app.core.config import Settings
from finance_app.providers.base import BankProvider
from finance_app.providers.mock import MockProvider
from finance_app.providers.yapily import YapilyProvider


def build_provider(settings: Settings) -> BankProvider:
    """Create the provider named by ``BANK_PROVIDER``.

    Args:
        settings: Application settings.

    Returns:
        A ready provider. Call ``close_provider`` on shutdown.
    """
    if settings.bank_provider == "yapily":
        return YapilyProvider.from_settings(settings)
    return MockProvider(settings.public_api_url)


async def close_provider(provider: BankProvider) -> None:
    """Release a provider's resources (HTTP connections), if it holds any."""
    if isinstance(provider, YapilyProvider):
        await provider.aclose()
