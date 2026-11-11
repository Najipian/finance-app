"""Bank connection use cases: list banks, start consent, handle the callback (BR-02).

Flow: ``start`` creates a *pending* connection, binds a single-use ``state`` to it
in Redis, and returns the bank's authorisation URL. The bank redirects the
browser to the callback; ``complete`` consumes the state, finishes the consent
with the provider, encrypts the consent token, activates the connection and
queues the first account sync. A cancelled consent deletes the pending row, so
no data is kept.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlencode

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.config import Settings
from finance_app.core.crypto import TokenCipher
from finance_app.core.errors import DomainError, NotFoundError
from finance_app.core.jobs import JobQueue
from finance_app.modules.connections.models import BankConnection, ConnectionStatus
from finance_app.modules.connections.repository import ConnectionRepository
from finance_app.modules.connections.state import ConsentStateStore, StateBinding
from finance_app.providers.base import (
    BankProvider,
    ConsentRejectedError,
    Institution,
    ProviderError,
)

log = structlog.get_logger(__name__)


class ProviderUnavailableError(DomainError):
    """The Open Banking provider failed; the user can retry later."""

    status_code = 502
    title = "Bank provider unavailable"


class InstitutionNotFoundError(NotFoundError):
    """The institution doesn't exist (in that country) at the provider."""

    def __init__(self) -> None:
        super().__init__("Unknown institution.")


class CallbackOutcome(StrEnum):
    """Result of the consent callback, passed to the web app in the redirect."""

    CONNECTED = "connected"
    CANCELLED = "cancelled"
    ERROR = "error"
    INVALID_STATE = "invalid_state"


@dataclass(frozen=True, slots=True)
class CallbackResult:
    """What happened on the callback, and for which connection (if known)."""

    outcome: CallbackOutcome
    connection_id: uuid.UUID | None = None


class ConnectionService:
    """Use cases for connecting banks.

    Args:
        session: Database session for this request.
        provider: The configured Open Banking provider.
        cipher: Encrypts consent tokens before storage.
        states: Single-use consent ``state`` store.
        jobs: Queue for background syncs.
        settings: Public URLs and country defaults.
    """

    def __init__(
        self,
        session: AsyncSession,
        provider: BankProvider,
        cipher: TokenCipher,
        states: ConsentStateStore,
        jobs: JobQueue,
        settings: Settings,
    ) -> None:
        self._session = session
        self._provider = provider
        self._cipher = cipher
        self._states = states
        self._jobs = jobs
        self._settings = settings
        self._connections = ConnectionRepository(session)

    async def list_institutions(self, country: str) -> list[Institution]:
        """Banks available in a country.

        Raises:
            ProviderUnavailableError: The provider failed.
        """
        try:
            return await self._provider.list_institutions(country)
        except ProviderError as exc:
            log.warning("provider_error", operation="list_institutions", error=str(exc))
            raise ProviderUnavailableError("Could not load banks. Try again later.") from exc

    async def start(
        self, user_id: uuid.UUID, institution_id: str, country: str = "GB"
    ) -> tuple[BankConnection, str]:
        """Start connecting a bank.

        Args:
            user_id: The signed-in user.
            institution_id: Provider ID of the bank.
            country: Country used to validate the institution.

        Returns:
            The pending connection and the bank authorisation URL.

        Raises:
            InstitutionNotFoundError: Unknown institution.
            ProviderUnavailableError: The provider failed.
        """
        institutions = await self.list_institutions(country)
        institution = next((i for i in institutions if i.id == institution_id), None)
        if institution is None:
            raise InstitutionNotFoundError

        connection = BankConnection(
            id=uuid.uuid4(),
            user_id=user_id,
            provider=self._provider.name,
            institution_id=institution.id,
            institution_name=institution.name,
            status=ConnectionStatus.PENDING,
        )
        self._connections.add(connection)
        state = await self._states.issue(StateBinding(user_id, connection.id))
        callback = (
            f"{self._settings.public_api_url.rstrip('/')}/api/v1/connections/callback?"
            + urlencode({"state": state})
        )
        try:
            consent = await self._provider.create_consent(str(user_id), institution.id, callback)
        except ProviderError as exc:
            await self._session.rollback()
            log.warning("provider_error", operation="create_consent", error=str(exc))
            raise ProviderUnavailableError("Could not contact the bank. Try again.") from exc
        await self._session.commit()
        log.info("consent_started", user_id=str(user_id), connection_id=str(connection.id))
        return connection, consent.authorisation_url

    async def complete(self, callback_params: Mapping[str, str]) -> CallbackResult:
        """Finish a consent from the bank's redirect.

        Args:
            callback_params: All query parameters of the callback request.

        Returns:
            The outcome; never raises for user-caused problems, so the browser can
            always be redirected to a page that explains what happened.
        """
        binding = await self._states.consume(callback_params.get("state", ""))
        if binding is None:
            log.warning("consent_state_invalid")
            return CallbackResult(CallbackOutcome.INVALID_STATE)
        connection = await self._connections.get_for_user(binding.connection_id, binding.user_id)
        if connection is None or connection.status is not ConnectionStatus.PENDING:
            log.warning("consent_state_stale", connection_id=str(binding.connection_id))
            return CallbackResult(CallbackOutcome.INVALID_STATE)

        provider_params = {k: v for k, v in callback_params.items() if k != "state"}
        try:
            consent = await self._provider.complete_consent(provider_params)
        except ConsentRejectedError as exc:
            await self._connections.delete(connection)
            await self._session.commit()
            log.info("consent_cancelled", connection_id=str(connection.id), reason=exc.reason)
            return CallbackResult(CallbackOutcome.CANCELLED, connection.id)
        except ProviderError as exc:
            await self._connections.delete(connection)
            await self._session.commit()
            log.warning("consent_failed", connection_id=str(connection.id), error=str(exc))
            return CallbackResult(CallbackOutcome.ERROR, connection.id)

        connection.consent_token_enc = self._cipher.encrypt(
            consent.consent_token.get_secret_value(), associated_data=connection.id.bytes
        )
        connection.provider_consent_id = consent.consent_id
        connection.consent_expires_at = consent.expires_at
        connection.status = ConnectionStatus.ACTIVE
        await self._session.commit()
        await self._jobs.enqueue_account_sync(connection.id)
        log.info("consent_granted", user_id=str(binding.user_id), connection_id=str(connection.id))
        return CallbackResult(CallbackOutcome.CONNECTED, connection.id)

    async def list_connections(self, user_id: uuid.UUID) -> Sequence[BankConnection]:
        """The user's bank connections."""
        return await self._connections.list_for_user(user_id)

    def web_redirect_url(self, result: CallbackResult) -> str:
        """Where to send the browser after the callback."""
        params = {"status": result.outcome.value}
        if result.connection_id and result.outcome is CallbackOutcome.CONNECTED:
            params["connection_id"] = str(result.connection_id)
        return f"{self._settings.web_app_url.rstrip('/')}/connections/result?{urlencode(params)}"
