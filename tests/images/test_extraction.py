import asyncio
import logging

import pytest

from agent.modules.images.image_data import Accepte, ReasonRejet, Reject, extraction

from .fakes import SECRET, FakeVLM

RETENTABLE = Reject(ReasonRejet.JSON_INVALIDE, retryable=True)
DEFINITIF = Reject(ReasonRejet.CHAMP_INTERDIT, retryable=False)


def valideur(*resultats):
    it = iter(resultats)
    appels = []

    def _v(brut):
        appels.append(brut)
        return next(it)
    _v.appels = appels
    return _v


async def test_succes_un_seul_appel():
    vlm, v = FakeVLM("brut"), valideur(Accepte("ok"))
    r = await extraction(b"img", "prompt", vlm, v)
    assert isinstance(r, Accepte) and len(vlm.appels) == 1


async def test_un_retry_puis_succes():
    vlm, v = FakeVLM("a", "b"), valideur(RETENTABLE, Accepte("ok"))
    r = await extraction(b"img", "prompt", vlm, v)
    assert isinstance(r, Accepte) and len(vlm.appels) == 2


async def test_jamais_plus_de_deux_appels():
    vlm, v = FakeVLM("a"), valideur(RETENTABLE, RETENTABLE, RETENTABLE)
    r = await extraction(b"img", "prompt", vlm, v)
    assert isinstance(r, Reject) and len(vlm.appels) == 2


async def test_rejet_definitif_sans_retry():
    vlm, v = FakeVLM("a"), valideur(DEFINITIF)
    r = await extraction(b"img", "prompt", vlm, v)
    assert r == DEFINITIF and len(vlm.appels) == 1


async def test_erreur_fournisseur_devient_un_rejet():
    vlm, v = FakeVLM(RuntimeError("503")), valideur()
    r = await extraction(b"img", "prompt", vlm, v)
    assert isinstance(r, Reject) and r.reason == ReasonRejet.ERREUR_FOURNISSEUR
    assert v.appels == []                     # rien à valider


async def test_l_annulation_n_est_pas_avalee():
    with pytest.raises(asyncio.CancelledError):
        await extraction(b"img", "p", FakeVLM(asyncio.CancelledError()), valideur())


async def test_brut_non_journalise(caplog):
    caplog.set_level(logging.DEBUG)
    await extraction(b"img", "p", FakeVLM(SECRET), valideur(RETENTABLE, RETENTABLE))
    assert SECRET not in caplog.text


async def test_message_d_exception_non_journalise(caplog):
    caplog.set_level(logging.DEBUG)
    await extraction(b"img", "p", FakeVLM(RuntimeError(SECRET)), valideur())
    assert SECRET not in caplog.text
