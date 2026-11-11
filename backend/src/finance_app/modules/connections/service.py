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
from finance_app.core.errors import ConflictError, DomainError, NotFoundError
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

_RENEWABLE = {ConnectionStatus.ACTIVE, ConnectionStatus.NEEDS_RENEWAL}


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
        try:
            consent = await self._provider.create_consent(
                str(user_id), institution.id, self._callback_url(state)
            )
        except ProviderError as exc:
            await self._session.rollback()
            log.warning("provider_error", operation="create_consent", error=str(exc))
            raise ProviderUnavailableError("Could not contact the bank. Try again.") from exc
        await self._session.commit()
        log.info("consent_started", user_id=str(user_id), connection_id=str(connection.id))
        return connection, consent.authorisation_url

    async def complete(self, callback_params: Mapping[str, str]) -> CallbackResult:
        """Finish a consent (new connection or renewal) from the bank's redirect.

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
        expected = _RENEWABLE if binding.renew else {ConnectionStatus.PENDING}
        if connection is None or connection.status not in expected:
            log.warning("consent_state_stale", connection_id=str(binding.connection_id))
            return CallbackResult(CallbackOutcome.INVALID_STATE)

        provider_params = {k: v for k, v in callback_params.items() if k != "state"}
        try:
            consent = await self._provider.complete_consent(provider_params)
        except ProviderError as exc:
            outcome = (
                CallbackOutcome.CANCELLED
                if isinstance(exc, ConsentRejectedError)
                else CallbackOutcome.ERROR
            )
            if not binding.renew:
                # A new connection that was never approved: keep nothing (US-01).
                await self._connections.delete(connection)
                await self._session.commit()
            # A cancelled renewal leaves the existing connection and its data alone.
            log.info("consent_not_granted", connection_id=str(connection.id), outcome=outcome)
            return CallbackResult(outcome, connection.id)

        superseded_consent_id = connection.provider_consent_id if binding.renew else None
        connection.consent_token_enc = self._cipher.encrypt(
            consent.consent_token.get_secret_value(), associated_data=connection.id.bytes
        )
        connection.provider_consent_id = consent.consent_id
        connection.consent_expires_at = consent.expires_at
        connection.status = ConnectionStatus.ACTIVE
        await self._session.commit()
        await self._jobs.enqueue_sync(connection.id)
        if superseded_consent_id and superseded_consent_id != consent.consent_id:
            await self._jobs.enqueue_revoke(connection.provider, superseded_consent_id)
        log.info(
            "consent_renewed" if binding.renew else "consent_granted",
            user_id=str(binding.user_id),
            connection_id=str(connection.id),
        )
        return CallbackResult(CallbackOutcome.CONNECTED, connection.id)

    async def start_renewal(self, user_id: uuid.UUID, connection_id: uuid.UUID) -> str:
        """Start re-consent for an existing connection (BR-03).

        Returns:
            The bank authorisation URL.

        Raises:
            NotFoundError: No such connection for this user.
            ConflictError: The connection can't be renewed.
            ProviderUnavailableError: The provider failed.
        """
        connection = await self._owned(user_id, connection_id)
        if connection.status not in _RENEWABLE:
            raise ConflictError("This connection can't be renewed.")
        state = await self._states.issue(StateBinding(user_id, connection.id, renew=True))
        try:
            consent = await self._provider.create_consent(
                str(user_id), connection.institution_id, self._callback_url(state)
            )
        except ProviderError as exc:
            log.warning("provider_error", operation="create_consent", error=str(exc))
            raise ProviderUnavailableError("Could not contact the bank. Try again.") from exc
        log.info("renewal_started", user_id=str(user_id), connection_id=str(connection.id))
        return consent.authorisation_url

    async def disconnect(self, user_id: uuid.UUID, connection_id: uuid.UUID) -> None:
        """Revoke consent at the provider and delete the bank's data (BR-04).

        Local data is deleted immediately even if the provider is unreachable; the
        revocation is then retried in the background.

        Raises:
            NotFoundError: No such connection for this user.
        """
        connection = await self._owned(user_id, connection_id)
        consent_id, provider = connection.provider_consent_id, connection.provider
        if consent_id:
            try:
                await self._provider.revoke_consent(consent_id)
            except ProviderError as exc:
                log.warning("revoke_deferred", connection_id=str(connection_id), error=str(exc))
                await self._jobs.enqueue_revoke(provider, consent_id)
        await self._connections.delete(connection)  # accounts, balances, transactions cascade
        await self._session.commit()
        log.info("connection_deleted", user_id=str(user_id), connection_id=str(connection_id))

    async def request_sync(self, user_id: uuid.UUID, connection_id: uuid.UUID) -> bool:
        """Queue a manual sync.

        Returns:
            True if queued; False if one is already queued for this minute.

        Raises:
            NotFoundError: No such connection for this user.
            ConflictError: The connection isn't active (e.g. needs renewal).
        """
        connection = await self._owned(user_id, connection_id)
        if connection.status is not ConnectionStatus.ACTIVE:
            raise ConflictError("Renew this connection before syncing.")
        return await self._jobs.enqueue_sync(connection.id)

    async def _owned(self, user_id: uuid.UUID, connection_id: uuid.UUID) -> BankConnection:
        """The user's connection, or 404 (never reveal other users' connections)."""
        connection = await self._connections.get_for_user(connection_id, user_id)
        if connection is None or connection.status is ConnectionStatus.PENDING:
            raise NotFoundError("Connection not found.")
        return connection

    def _callback_url(self, state: str) -> str:
        return (
            f"{self._settings.public_api_url.rstrip('/')}/api/v1/connections/callback?"
            + urlencode({"state": state})
        )

    async def list_connections(self, user_id: uuid.UUID) -> Sequence[BankConnection]:
        """The user's bank connections."""
        return await self._connections.list_for_user(user_id)

    def web_redirect_url(self, result: CallbackResult) -> str:
        """Where to send the browser after the callback."""
        params = {"status": result.outcome.value}
        if result.connection_id and result.outcome is CallbackOutcome.CONNECTED:
            params["connection_id"] = str(result.connection_id)
        return f"{self._settings.web_app_url.rstrip('/')}/connections/result?{urlencode(params)}"
