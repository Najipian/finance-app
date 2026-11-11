"""Demo bank approval page for the mock provider (never mounted in production).

Plays the part of the bank's consent screen: Approve redirects to our callback
with a one-time token, Cancel redirects with ``error=access_denied`` (the same
shape Yapily uses), so the full consent flow works offline.
"""

from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from finance_app.api.deps import AppSettings
from finance_app.core.errors import DomainError
from finance_app.providers.mock import INSTITUTIONS, MockProvider

router = APIRouter(prefix="/mock-bank", tags=["mock bank (demo only)"], include_in_schema=False)


class InvalidMockRequestError(DomainError):
    """The mock bank was called with an unknown bank or a foreign callback URL."""


@router.get("/authorize", response_class=HTMLResponse)
async def authorize(
    settings: AppSettings,
    institution: str = Query(max_length=64),
    callback: str = Query(max_length=2048),
) -> HTMLResponse:
    """Show the mock consent screen."""
    own_callback = f"{settings.public_api_url.rstrip('/')}/api/v1/connections/callback?"
    if not callback.startswith(own_callback):
        # Only ever redirect to our own callback: no open redirect.
        raise InvalidMockRequestError("Callback must be this API's consent callback.")
    bank = next((i for i in INSTITUTIONS if i.id == institution), None)
    if bank is None:
        raise InvalidMockRequestError("Unknown mock institution.")

    approve = f"{callback}&{urlencode({'one-time-token': MockProvider.one_time_token(bank.id)})}"
    cancel = f"{callback}&{urlencode({'error': 'access_denied', 'error-source': 'user'})}"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(bank.name)} · consent</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 28rem; margin: 3rem auto; padding: 0 1rem;
         color: #1b1f24; background: #f6f7f9; }}
  .card {{ background: #fff; border-radius: 12px; padding: 1.5rem; box-shadow: 0 1px 4px #0002; }}
  .demo {{ font-size: .8rem; color: #8a5a00; background: #fff4d6; padding: .4rem .6rem;
          border-radius: 6px; display: inline-block; }}
  a {{ display: inline-block; margin: .5rem .5rem 0 0; padding: .6rem 1.1rem; border-radius: 8px;
       text-decoration: none; font-weight: 600; }}
  .approve {{ background: #0b6b3a; color: #fff; }}
  .cancel {{ background: #e7e9ee; color: #1b1f24; }}
</style></head>
<body><div class="card">
  <span class="demo">Demo bank: no real data</span>
  <h1>{escape(bank.name)}</h1>
  <p><strong>Onesum</strong> is asking to read your accounts, balances and transactions
     for 90 days. It cannot move money.</p>
  <a class="approve" href="{escape(approve)}">Approve</a>
  <a class="cancel" href="{escape(cancel)}">Cancel</a>
</div></body></html>"""
    return HTMLResponse(page)
