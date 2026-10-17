import logging

import pytest

import gemini_signals


class FakeModels:
    def __init__(self, error=None):
        self.error = error

    def generate_content(self, **kwargs):
        if self.error:
            raise self.error
        raise AssertionError("not expected")


@pytest.fixture
def fake_client(monkeypatch):
    seen = {}

    def install(error=None):
        from google import genai

        class FakeClient:
            def __init__(self, api_key, http_options=None):
                seen["api_key"] = api_key
                self.models = FakeModels(error)

        monkeypatch.setattr(genai, "Client", FakeClient)
        return seen

    return install


def test_timeout_meets_geminis_10_second_minimum():
    # Gemini rejects any deadline under 10s with 400 INVALID_ARGUMENT.
    assert gemini_signals.TIMEOUT_MS >= 10_000


def test_missing_key_is_logged_once(monkeypatch, caplog):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gemini_signals, "_warned_no_key", False)
    caplog.set_level(logging.INFO)
    assert gemini_signals.scam_signals("hello") is None
    assert gemini_signals.scam_signals("hello again") is None
    assert caplog.text.count("GEMINI_API_KEY is not set") == 1


def test_pasted_key_is_cleaned_up(monkeypatch, fake_client):
    monkeypatch.setenv("GEMINI_API_KEY", '  "abc123"\n')
    seen = fake_client(error=RuntimeError("boom"))
    gemini_signals.scam_signals("hello")
    assert seen["api_key"] == "abc123"


def test_failures_are_logged_without_the_key(monkeypatch, fake_client, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key-123")
    fake_client(error=RuntimeError("400 API key not valid. key=secret-key-123"))
    caplog.set_level(logging.INFO)
    assert gemini_signals.scam_signals("hello") is None
    assert "Gemini check failed: RuntimeError: 400 API key not valid" in caplog.text
    assert "secret-key-123" not in caplog.text
