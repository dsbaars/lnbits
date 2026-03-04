import pytest
from pytest_mock.plugin import MockerFixture
from unittest.mock import AsyncMock, Mock

from lnbits.core.models.lnurl import CreateLnurlPayment
from lnbits.core.services.lnurl import fetch_lnurl_pay_request


LIGHTNING_ADDRESS_CALLBACK_PAYLOAD = {
    "pr": (
        "lnbc1pnsu5z3pp57getmdaxhg5kc9yh2a2qsh7cjf4gnccgkw0qenm8vsqv50w7s"
        "ygqdqj0fjhymeqv9kk7atwwscqzzsxqyz5vqsp5e2yyqcp0a3ujeesp24ya0glej"
        "srh703md8mrx0g2lyvjxy5w27ss9qxpqysgqyjreasng8a086kpkczv48er5c6l5"
        "73aym6ynrdl9nkzqnag49vt3sjjn8qdfq5cr6ha0vrdz5c5r3v4aghndly0hplmv"
        "6hjxepwp93cq398l3s"
    ),
    "successAction": {
        "tag": "message",
        "message": "LNURL pay to user@example.com",
    },
    "disposable": False,
}


@pytest.mark.anyio
async def test_fetch_lnurl_pay_request_lightning_address_callback_payload(
    mocker: MockerFixture,
):
    """
    Use an LNURL-pay (Lightning Address style) callback payload without a
    ``status`` field and verify that our LNURL pay helper can handle it.
    """

    # Prepare an AsyncClient mock used by the underlying lnurl library.
    mock_async_client = AsyncMock()
    mock_async_client.__aenter__.return_value = mock_async_client

    call_counter = {"count": 0}

    async def mock_get(url, *_, **__):
        """
        First GET: lnurl metadata (payRequest).
        Second GET: callback payload with PR / successAction / disposable.
        """
        call_counter["count"] += 1
        response = Mock()
        response.is_error = False

        if call_counter["count"] == 1:
            # LNURL pay metadata response for the address.
            response.json.return_value = {
                "tag": "payRequest",
                "callback": "https://example.com/lnurl/callback",
                "minSendable": 1000,
                "maxSendable": 1_500_000,
                "metadata": (
                    '[["text/plain", "LNURL pay to user@example.com"]]'
                ),
            }
        else:
            # Callback response from the Lightning Address service itself.
            response.json.return_value = LIGHTNING_ADDRESS_CALLBACK_PAYLOAD

        return response

    mock_async_client.get.side_effect = mock_get
    mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    # Create minimal LNURL payment data for an address.
    data = CreateLnurlPayment(
        lnurl="user@example.com",
        amount=1000,
        unit="sat",
        comment=None,
    )

    # If this raises (for example because a ``status`` field is wrongly required),
    # the test will fail and expose the bug.
    _, res2 = await fetch_lnurl_pay_request(data=data, wallet=None)

    assert res2.pr == LIGHTNING_ADDRESS_CALLBACK_PAYLOAD["pr"]
    assert res2.successAction is not None
    assert res2.disposable is False

