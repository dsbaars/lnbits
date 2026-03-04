from unittest.mock import AsyncMock, Mock

import pytest
from lnurl import LnurlResponseException
from pytest_mock.plugin import MockerFixture

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
) -> None:
    """
    Happy path: LNURL-pay (Lightning Address style) callback payload without a
    ``status`` field is accepted and parsed correctly.
    """

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__.return_value = mock_async_client

    call_counter = {"count": 0}

    async def mock_get(url, *_, **__) -> Mock:
        """
        1st GET: LNURL-pay metadata (payRequest).
        2nd GET: callback payload with PR / successAction / disposable.
        """
        call_counter["count"] += 1
        response = Mock()
        response.is_error = False

        if call_counter["count"] == 1:
            # LNURL-pay metadata response, per LUD-06 base spec.
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
            # Callback response from the service: PR + successAction + disposable.
            response.json.return_value = LIGHTNING_ADDRESS_CALLBACK_PAYLOAD

        return response

    mock_async_client.get.side_effect = mock_get
    mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    data = CreateLnurlPayment(
        lnurl="user@example.com",
        amount=1000,
        unit="sat",
        comment=None,
    )

    # If this raises (for example because a ``status`` field is wrongly required),
    # the test will fail and expose the bug.
    res, res2 = await fetch_lnurl_pay_request(data=data, wallet=None)

    # Validate metadata structure according to LUD-06:
    # metadata is a JSON string representing a list of lists, where the first
    # entry must be ["text/plain", <short description>].
    metadata_list = res.metadata.list()
    assert isinstance(metadata_list, list)
    assert len(metadata_list) >= 1
    assert metadata_list[0][0] == "text/plain"
    assert metadata_list[0][1] == "LNURL pay to user@example.com"

    # And the callback payload without "status" must still be handled correctly.
    assert res2.pr == LIGHTNING_ADDRESS_CALLBACK_PAYLOAD["pr"]
    assert res2.successAction is not None
    assert res2.disposable is False


@pytest.mark.anyio
async def test_fetch_lnurl_pay_request_error_response_callback(
    mocker: MockerFixture,
) -> None:
    """
    Error path: payRequest metadata is valid, but the *callback* returns the
    error variant from LUD-06:

        {"status": "ERROR", "reason": "error details..."}

    This should surface as an LnurlResponseException from fetch_lnurl_pay_request.
    """

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__.return_value = mock_async_client

    call_counter = {"count": 0}

    async def mock_get(url, *_, **__) -> Mock:
        call_counter["count"] += 1
        response = Mock()
        response.is_error = False

        if call_counter["count"] == 1:
            # Valid payRequest metadata, per LUD-06.
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
            # Callback returns an error instead of an invoice.
            response.json.return_value = {
                "status": "ERROR",
                "reason": "error details...",
            }

        return response

    mock_async_client.get.side_effect = mock_get
    mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    data = CreateLnurlPayment(
        lnurl="user@example.com",
        amount=1000,
        unit="sat",
        comment=None,
    )

    with pytest.raises(LnurlResponseException) as exc:
        await fetch_lnurl_pay_request(data=data, wallet=None)

    assert "error details..." in str(exc.value)


@pytest.mark.anyio
async def test_fetch_lnurl_pay_request_error_first_response(
    mocker: MockerFixture,
) -> None:
    """
    Error path: the *first* response from the LNURL service is already the
    LUD-06 error form:

        {"status": "ERROR", "reason": "error details..."}

    In this case fetch_lnurl_pay_request should fail before any callback
    invocation, surfacing an LnurlResponseException with the reason.
    """

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__.return_value = mock_async_client

    async def mock_get(url, *_, **__) -> Mock:
        response = Mock()
        response.is_error = False
        # First (and only) call: directly return the error object instead of
        # a payRequest metadata object.
        response.json.return_value = {
            "status": "ERROR",
            "reason": "error details...",
        }
        return response

    mock_async_client.get.side_effect = mock_get
    mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    data = CreateLnurlPayment(
        lnurl="user@example.com",
        amount=1000,
        unit="sat",
        comment=None,
    )

    with pytest.raises(LnurlResponseException) as exc:
        await fetch_lnurl_pay_request(data=data, wallet=None)

    assert "error details..." in str(exc.value)

