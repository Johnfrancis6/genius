import base64
import logging
from types import SimpleNamespace

import pytest

from agent.core import llm

SECRET = "SECRET-DANS-L-ERREUR-123"
MSG = [{"role": "user", "content": "CONTENU-SENSIBLE"}]
MSG_JSON = [{"role": "user", "content": "Réponds en JSON."}]


class FakeCompletions:
    def __init__(self, contenu="ok", erreur=None):
        self.contenu = contenu
        self.erreur = erreur
        self.appels: list[dict] = []

    async def create(self, **kwargs):
        self.appels.append(kwargs)
        if self.erreur is not None:
            raise self.erreur
        message = SimpleNamespace(content=self.contenu)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def client(monkeypatch):
    def installer(**kw):
        completions = FakeCompletions(**kw)
        faux = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        monkeypatch.setattr(llm, "_client", faux)
        return completions

    return installer


# --- detecter_mime ---


@pytest.mark.parametrize(
    ("data", "attendu"),
    [
        (b"\xff\xd8\xffreste", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nreste", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPreste", "image/webp"),
    ],
)
def test_detecter_mime(data, attendu):
    assert llm.detecter_mime(data) == attendu


@pytest.mark.parametrize(
    "data", [b"GIF89a-reste", b"RIFF\x00\x00\x00\x00WAVEreste", b"", b"\xff\xd8"]
)
def test_detecter_mime_refuse(data):
    with pytest.raises(llm.LLMError):
        llm.detecter_mime(data)


# --- complete_text ---


async def test_complete_text_ok(client, caplog):
    c = client(contenu="Bonjour !")
    with caplog.at_level(logging.INFO, logger=llm.logger.name):
        assert await llm.complete_text(MSG, model="m-test") == "Bonjour !"
    k = c.appels[0]
    assert k["model"] == "m-test"
    assert k["timeout"] == llm.TIMEOUT_TEXTE_S
    assert k["max_completion_tokens"] == llm.MAX_TOKENS_TEXTE
    assert k["stream"] is False
    assert "response_format" not in k and "temperature" not in k
    assert "CONTENU-SENSIBLE" not in caplog.text and "Bonjour" not in caplog.text


async def test_complete_text_json_et_temperature(client):
    c = client(contenu="{}")
    await llm.complete_text(MSG_JSON, model="m", json_mode=True, temperature=0.2)
    k = c.appels[0]
    assert k["response_format"] == {"type": "json_object"}
    assert k["temperature"] == 0.2


async def test_json_mode_sans_le_mot_json(client):
    c = client()
    with pytest.raises(llm.LLMError):
        await llm.complete_text(MSG, model="m", json_mode=True)
    assert c.appels == []  # refus avant tout appel réseau


async def test_erreur_sdk_devient_llm_error(client, caplog):
    client(erreur=RuntimeError(SECRET))
    with caplog.at_level(logging.INFO, logger=llm.logger.name):
        with pytest.raises(llm.LLMError) as e:
            await llm.complete_text(MSG, model="m")
    assert SECRET not in str(e.value) and e.value.__cause__ is None
    assert SECRET not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("contenu", ["", "  \n ", None])
async def test_reponse_vide(client, contenu):
    client(contenu=contenu)
    with pytest.raises(llm.LLMError):
        await llm.complete_text(MSG, model="m")


async def test_reglages_invalides(client, monkeypatch):
    client()

    def casse():
        raise ValueError(SECRET)

    monkeypatch.setattr(llm, "get_setting", casse)
    with pytest.raises(llm.LLMError) as e:
        await llm.complete_text(MSG)  # sans model : lit GROQ_MODEL_TEXT
    assert SECRET not in str(e.value)


# --- appel_vlm ---


async def test_appel_vlm(client, monkeypatch):
    monkeypatch.setattr(llm, "_reglage", lambda nom: "vlm-test")
    c = client(contenu="{}")
    image = b"\xff\xd8\xffdata"
    assert await llm.appel_vlm(image, "Décris en JSON") == "{}"
    k = c.appels[0]
    assert k["model"] == "vlm-test"
    assert k["timeout"] == llm.TIMEOUT_VISION_S
    assert k["max_completion_tokens"] == llm.MAX_TOKENS_VISION
    assert k["extra_body"] == {"reasoning_effort": "none"}
    parts = k["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Décris en JSON"}
    attendu = "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")
    assert parts[1]["image_url"]["url"] == attendu


async def test_appel_vlm_format_invalide(client):
    c = client()
    with pytest.raises(llm.LLMError):
        await llm.appel_vlm(b"GIF89a-reste", "prompt")
    assert c.appels == []


def test_reset_client(monkeypatch):
    monkeypatch.setattr(llm, "_client", object())
    llm.reset_client()
    assert llm._client is None
