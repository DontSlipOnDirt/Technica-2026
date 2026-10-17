import logging

import pytest
from google.genai import errors

import gemini_signals
from gemini_signals import GeminiUnavailable, ScamSignals

SCAM = ScamSignals(impersonation=True, pressure=True, unusual_payment=True, evidence=["Microsoft support"])


class FakeResponse:
    def __init__(self, parsed):
        self.parsed = parsed


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    gemini_signals._cache.clear()
    monkeypatch.setattr(gemini_signals, "_warned_no_key", False)


@pytest.fixture
def fake_gemini(monkeypatch):
    """Replies with each item in turn: an exception is raised, anything else is the parsed answer."""
    seen = {"calls": 0, "api_key": None, "model": None}

    def install(*replies):
        from google import genai

        class FakeModels:
            def generate_content(self, model, **kwargs):
                seen["model"] = model
                reply = replies[min(seen["calls"], len(replies) - 1)]
                seen["calls"] += 1
                if isinstance(reply, Exception):
                    raise reply
                return FakeResponse(reply)

        class FakeClient:
            def __init__(self, api_key, http_options=None):
                seen["api_key"] = api_key
                self.models = FakeModels()

        monkeypatch.setattr(genai, "Client", FakeClient)
        return seen

    return install


def server_error():
    return errors.ServerError(504, {"error": {"code": 504, "message": "Deadline expired", "status": "DEADLINE_EXCEEDED"}})


def client_error():
    return errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}})


# ---- Model and timeout ---------------------------------------------------------------

def test_default_model_is_the_fast_one(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert gemini_signals._model() == "gemini-flash-lite-latest"


def test_timeout_meets_geminis_10_second_minimum():
    # Gemini rejects any deadline under 10s with 400 INVALID_ARGUMENT.
    assert gemini_signals.TIMEOUT_MS >= 10_000


# ---- No key: Gemini is simply off ----------------------------------------------------

def test_missing_key_means_off_and_is_logged_once(monkeypatch, caplog):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    caplog.set_level(logging.INFO)
    assert gemini_signals.scam_signals("hello") is None
    gemini_signals.prefetch("hello again")
    assert gemini_signals.scam_signals("hello again") is None
    assert caplog.text.count("GEMINI_API_KEY is not set") == 1


def test_pasted_key_is_cleaned_up(monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", '  "abc123"\n')
    seen = fake_gemini(SCAM)
    gemini_signals.scam_signals("hello")
    assert seen["api_key"] == "abc123"


# ---- Retries and failures --------------------------------------------------------------

def test_a_server_error_is_retried_once(monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = fake_gemini(server_error(), SCAM)
    assert gemini_signals.scam_signals("hello") == SCAM
    assert seen["calls"] == 2


def test_a_bad_request_is_not_retried(monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = fake_gemini(client_error(), SCAM)
    with pytest.raises(GeminiUnavailable):
        gemini_signals.scam_signals("hello")
    assert seen["calls"] == 1


def test_two_failures_mean_unavailable_and_are_logged_without_the_key(monkeypatch, fake_gemini, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key-123")
    fake_gemini(RuntimeError("timed out, key=secret-key-123"))
    caplog.set_level(logging.INFO)
    with pytest.raises(GeminiUnavailable):
        gemini_signals.scam_signals("hello")
    assert "Gemini check failed: RuntimeError: timed out" in caplog.text
    assert "secret-key-123" not in caplog.text


def test_an_empty_answer_counts_as_unavailable(monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    fake_gemini(None)
    with pytest.raises(GeminiUnavailable):
        gemini_signals.scam_signals("hello")


# ---- Checking early, while the customer is still talking ---------------------------------

def test_prefetch_answer_is_reused(monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = fake_gemini(SCAM)
    gemini_signals.prefetch("he says he is from Microsoft")
    assert gemini_signals.scam_signals("he says he is from Microsoft") == SCAM
    assert seen["calls"] == 1


def test_new_words_get_a_new_check(monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = fake_gemini(SCAM)
    gemini_signals.prefetch("hello")
    gemini_signals.scam_signals("hello and more")
    assert seen["calls"] == 2


def test_cache_stays_small(monkeypatch, fake_gemini):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    fake_gemini(SCAM)
    for i in range(gemini_signals.CACHE_SIZE + 10):
        gemini_signals.prefetch(f"line {i}")
    assert len(gemini_signals._cache) <= gemini_signals.CACHE_SIZE


# ---- What the prompt tells Gemini to look for ------------------------------------------

@pytest.mark.parametrize("sign", [
    "tech support",          # "Microsoft support" / "Amazon security" calls
    "a company",             # impersonating any well-known company, not just the bank
    "courier or driver",     # cash handed to someone sent to collect it
    "keep it from their bank",
])
def test_prompt_names_the_scams_the_first_version_missed(sign):
    assert sign in gemini_signals.PROMPT


def test_prompt_maps_each_sign_to_a_field():
    # Rule 7 counts impersonation and unusual_payment, so the prompt says which sign goes where.
    for field in ("impersonation", "pressure", "unusual_payment"):
        assert f"{field}:" in gemini_signals.PROMPT
