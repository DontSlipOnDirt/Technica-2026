import httpx
import pytest

from nessie import NessieApiError, NessieClient


def client_with(handler):
    return NessieClient("test-key", base_url="https://example.test/", transport=httpx.MockTransport(handler))


def test_adds_the_api_key_and_decodes_json():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"_id": "account-1"}])

    accounts = client_with(handler).get("/customers/customer-1/accounts")
    assert accounts == [{"_id": "account-1"}]
    assert seen["url"] == "https://example.test/customers/customer-1/accounts?key=test-key"


def test_http_failures_raise_without_leaking_the_body():
    def handler(request):
        return httpx.Response(500, text="upstream failure")

    with pytest.raises(NessieApiError) as err:
        client_with(handler).get("/accounts/account-1")
    assert err.value.status == 500
    assert "upstream failure" not in str(err.value)


def test_post_sends_json():
    seen = {}

    def handler(request: httpx.Request):
        seen["method"] = request.method
        seen["body"] = request.content
        return httpx.Response(201, json={"code": 201})

    client_with(handler).post("/accounts/a1/transfers", {"amount": 50})
    assert seen["method"] == "POST"
    assert seen["body"] == b'{"amount":50}' or seen["body"] == b'{"amount": 50}'


def test_timeouts_become_nessie_errors():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(NessieApiError) as err:
        client_with(handler).get("/accounts/a1")
    assert err.value.status == 408


def test_params_are_passed_through():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[])

    client_with(handler).get("/merchants", params={"name": "Giant"})
    assert "name=Giant" in seen["url"] and "key=test-key" in seen["url"]


def test_the_api_key_never_reaches_the_logs(caplog):
    import logging
    caplog.set_level(logging.DEBUG)

    def handler(request):
        return httpx.Response(200, json={})

    client_with(handler).get("/accounts/a1")
    assert "test-key" not in caplog.text


def test_from_env_strips_spaces_and_quotes(monkeypatch):
    monkeypatch.setenv("NESSIE_API_KEY", '  "abc123"\n')
    assert NessieClient.from_env()._api_key == "abc123"
