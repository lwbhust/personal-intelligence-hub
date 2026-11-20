"""404/405/422 behaviour and unified error bodies (after successful auth)."""

from __future__ import annotations

import pytest

from support import Sidecar, assert_json_headers, http


def _assert_error(response, *, status_code: int, code: str, message: str) -> None:
    assert response.status_code == status_code
    assert_json_headers(response)
    assert response.json() == {"error": {"code": code, "message": message}}


def test_unknown_path_returns_not_found(sidecar: Sidecar) -> None:
    _assert_error(
        http(sidecar, path="/no-such-endpoint", token=sidecar.token),
        status_code=404,
        code="not_found",
        message="请求的资源不存在",
    )


def test_method_not_allowed(sidecar: Sidecar) -> None:
    _assert_error(
        http(sidecar, method="POST", path="/health", token=sidecar.token),
        status_code=405,
        code="method_not_allowed",
        message="请求方法不被允许",
    )


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_openapi_surfaces_are_disabled(sidecar: Sidecar, path: str) -> None:
    _assert_error(
        http(sidecar, path=path, token=sidecar.token),
        status_code=404,
        code="not_found",
        message="请求的资源不存在",
    )


def test_error_response_never_contains_token(sidecar: Sidecar) -> None:
    response = http(sidecar, path="/missing", token=sidecar.token)
    assert sidecar.token not in response.text
    assert "Traceback" not in response.text
