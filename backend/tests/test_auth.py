"""1. initData validatsiyasi va API auth."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api.auth import InitDataError, parse_auth, validate_init_data
from app.main import app
from tests.conftest import BOT_TOKEN, make_init_data


def test_valid_init_data_returns_user() -> None:
    user = validate_init_data(make_init_data(42, "Aziz"), BOT_TOKEN, max_age=3600)
    assert user.id == 42
    assert user.first_name == "Aziz"


def test_tampered_init_data_rejected() -> None:
    with pytest.raises(InitDataError, match="hash"):
        validate_init_data(make_init_data(tamper=True), BOT_TOKEN, max_age=3600)


def test_wrong_bot_token_rejected() -> None:
    with pytest.raises(InitDataError):
        validate_init_data(make_init_data(token="999:OTHER"), BOT_TOKEN, max_age=3600)


def test_expired_init_data_rejected() -> None:
    old = int(time.time()) - 10_000
    with pytest.raises(InitDataError, match="eskirgan"):
        validate_init_data(make_init_data(auth_date=old), BOT_TOKEN, max_age=3600)


@pytest.mark.parametrize("raw", ["", "foo=bar", "user=%7B%7D&auth_date=1"])
def test_garbage_init_data_rejected(raw: str) -> None:
    with pytest.raises(InitDataError):
        validate_init_data(raw, BOT_TOKEN, max_age=3600)


def test_dev_auth_disabled_outside_dev() -> None:
    with pytest.raises(InitDataError):
        parse_auth("dev:1")


def test_api_requires_init_data() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/me", headers={"Authorization": "tma bad"}).status_code == 401

        resp = client.get("/api/me", headers={"Authorization": f"tma {make_init_data(1001, 'Laylo')}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["telegram_id"] == 1001
        assert body["level"] == {"level": "A1", "next_level": "A2", "progress": 0}
        assert body["streak_days"] == 0

        progress = client.get("/api/progress", headers={"X-Telegram-Init-Data": make_init_data(1001)})
        assert progress.status_code == 200
        assert len(progress.json()["days"]) == 7


def test_settings_update_and_onboarding() -> None:
    with TestClient(app) as client:
        headers = {"Authorization": f"tma {make_init_data(2002, 'Nodira')}"}
        user = client.get("/api/me", headers=headers).json()["user"]
        assert user["onboarded"] is False and user["explain_lang"] == "uz" and user["needs_placement"] is False

        assert client.put("/api/settings", json={"explain_lang": "klingon"}, headers=headers).status_code == 422
        assert client.put("/api/settings", json={"goal": "travel"}).status_code == 401

        res = client.put(
            "/api/settings",
            json={"cefr_level": "A1", "needs_placement": True, "goal": "ielts", "explain_lang": "mix", "onboarded": True},
            headers=headers,
        ).json()
        assert res["onboarded"] and res["needs_placement"] and res["goal"] == "ielts" and res["explain_lang"] == "mix"

        res = client.put("/api/settings", json={"cefr_level": "B2", "speech_pace": "normal", "mic_mode": "ptt"}, headers=headers).json()
        assert res["cefr_level"] == "B2" and res["level_progress"] == 0 and res["needs_placement"] is False
        assert res["speech_pace"] == "normal" and res["mic_mode"] == "ptt"
