"""Bearer authentication tests: format, constant-time compare, auth-before-routing."""

from __future__ import annotations

import pytest

from support import Sidecar, assert_json_headers, http, make_token


def _assert_unauthorized(response, *, secret_values: tuple[str, ...]) -> None:
    assert response.status_code == 401
    assert_json_headers(response)
    body = response.json()
    assert body == {
        "error": {
            "code": "unauthorized",
            "message": "未授权：访问令牌缺失或无效",
        }
    }
    for secret in secret_values:
        assert secret not in response.text


def test_missing_authorization_header(sidecar: Sidecar) -> None:
    _assert_unauthorized(http(sidecar), secret_values=(sidecar.token,))


def test_wrong_token_is_rejected_without_echo(sidecar: Sidecar) -> None:
    wrong = make_token()
    _assert_unauthorized(
        http(sidecar, token=wrong),
        secret_values=(sidecar.token, wrong),
    )


@pytest.mark.parametrize(
    "build_value",
    [
        lambda token: "Bearer",
        lambda token: f"Bearer  {token}",  # two spaces
        lambda token: f"Bearer\t{token}",
        lambda token: token,
        lambda token: f"Basic {token}",
    ],
)
def test_malformed_authorization_headers(sidecar: Sidecar, build_value) -> None:
    value = build_value(sidecar.token)
    _assert_unauthorized(
        http(sidecar, raw_authorization=value),
        secret_values=(sidecar.token,),
    )


def test_scheme_is_case_insensitive(sidecar: Sidecar) -> None:
    response = http(sidecar, raw_authorization=f"bearer {sidecar.token}")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_precedes_routing(sidecar: Sidecar) -> None:
    # Unknown path without a token must be 401, never 404.
    _assert_unauthorized(
        http(sidecar, path="/definitely-not-a-route"),
        secret_values=(sidecar.token,),
    )
    # Wrong method without a token must be 401, never 405.
    _assert_unauthorized(
        http(sidecar, method="POST", path="/health"),
        secret_values=(sidecar.token,),
    )
