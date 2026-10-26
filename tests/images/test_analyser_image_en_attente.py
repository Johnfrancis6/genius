import pytest

from agent.modules.images import image_tool as m
from agent.modules.images.image_data import ReasonRejet, Reject

from .fakes import (
    INJECTION,
    SECRET,
    FakeExtracteur,
    FakeImageStore,
    FakeResultStore,
    FakeVLM,
    classif,
)

CLES = {
    "image_status",
    "image_type_detected",
    "image_result_id",
    "pending_image_id",
    "image_instruction",
}


async def analyser(state, images, resultats, vlm, extracteurs):
    return await m.analyser_image_en_attente(state, images, resultats, vlm, extracteurs)


async def test_cles_renvoyees(images, resultats, extracteurs, state):
    out = await analyser(state, images, resultats, FakeVLM(classif()), extracteurs)
    assert set(out) == CLES
    assert "urgency_level" not in out and "messages" not in out


async def test_extraction_reussie(images, resultats, extracteurs, state):
    out = await analyser(state, images, resultats, FakeVLM(classif()), extracteurs)
    assert out["image_status"] == m.Status.EXTRACTED.value
    assert out["image_type_detected"] == "ordonnance"
    assert out["image_result_id"] == "res-1" and out["pending_image_id"] is None
    assert out["image_instruction"] == m.MESSAGES[m.Status.EXTRACTED]
    assert len(resultats.recus) == 1 and images.supprimees == [("u1", "img1")]
    assert SECRET not in repr(out)


async def test_l_etat_n_est_pas_modifie(images, resultats, extracteurs, state):
    avant = dict(state)
    await analyser(state, images, resultats, FakeVLM(classif()), extracteurs)
    assert state == avant


@pytest.mark.parametrize("retire", ["user_id", "pending_image_id"])
async def test_aucune_image_en_attente(retire, images, resultats, extracteurs, state):
    vlm = FakeVLM(classif())
    etat = {k: v for k, v in state.items() if k != retire}
    out = await analyser(etat, images, resultats, vlm, extracteurs)
    assert out["image_status"] == m.Status.NO_IMAGE.value
    assert out["image_instruction"] == m.MESSAGES[m.Status.NO_IMAGE]
    assert out["pending_image_id"] is None and out["image_result_id"] is None
    assert vlm.appels == [] and images.supprimees == []


async def test_image_introuvable(resultats, extracteurs, state):
    vlm = FakeVLM(classif())
    out = await analyser(state, FakeImageStore(), resultats, vlm, extracteurs)
    assert out["image_status"] == m.Status.TECHNICAL_ERROR.value
    assert out["pending_image_id"] is None and vlm.appels == []


async def test_signe_medical_vu_par_le_classifieur(images, resultats, extracteurs, state):
    vlm = FakeVLM(classif(signe=True))
    out = await analyser(state, images, resultats, vlm, extracteurs)
    assert out["image_status"] == m.Status.MEDICAL_SIGN.value
    assert out["image_result_id"] is None and resultats.recus == []
    assert all(e.appels == 0 for e in extracteurs.values())
    assert images.supprimees == [("u1", "img1")]


async def test_signe_medical_rejete_par_l_extracteur(images, resultats, state):
    extracteur = FakeExtracteur(Reject(ReasonRejet.SIGNE_MEDICAL))
    extracteurs = {"ordonnance": extracteur, "piece_identite": extracteur}
    out = await analyser(state, images, resultats, FakeVLM(classif()), extracteurs)
    assert out["image_status"] == m.Status.MEDICAL_SIGN.value
    assert out["image_type_detected"] == "ordonnance"
    assert out["image_result_id"] is None
    assert resultats.recus == [] and extracteur.appels == 1
    assert images.supprimees == [("u1", "img1")]
    assert out["image_instruction"] == m.MESSAGES[m.Status.MEDICAL_SIGN]


async def test_erreur_d_ecriture_du_resultat(extracteurs, state):
    images = FakeImageStore({("u1", "img1"): b"x"})
    resultats = FakeResultStore(echec_put=True)
    out = await analyser(state, images, resultats, FakeVLM(classif()), extracteurs)
    assert out["image_status"] == m.Status.TECHNICAL_ERROR.value
    assert out["image_result_id"] is None and out["pending_image_id"] is None
    assert images.supprimees == [("u1", "img1")] and SECRET not in repr(out)


async def test_erreur_de_lecture_supprime_quand_meme(resultats, extracteurs, state):
    images = FakeImageStore({("u1", "img1"): b"x"}, echec_get=True)
    out = await analyser(state, images, resultats, FakeVLM(classif()), extracteurs)
    assert out["image_status"] == m.Status.TECHNICAL_ERROR.value
    assert images.supprimees == [("u1", "img1")] and SECRET not in repr(out)


async def test_echec_de_suppression_ne_masque_pas_le_resultat(resultats, extracteurs, state):
    images = FakeImageStore({("u1", "img1"): b"x"}, echec_delete=True)
    out = await analyser(state, images, resultats, FakeVLM(classif()), extracteurs)
    assert out["image_status"] == m.Status.EXTRACTED.value
    assert out["image_result_id"] == "res-1"


async def test_type_attendu_hors_liste_ignore(images, resultats, extracteurs, state):
    vlm = FakeVLM(classif("piece_identite"))
    out = await analyser(
        {**state, "expected_image_type": "admin"}, images, resultats, vlm, extracteurs
    )
    assert out["image_status"] == m.Status.TYPE_TO_CONFIRM.value
    assert all(e.appels == 0 for e in extracteurs.values())


async def test_type_different_de_l_attendu(images, resultats, extracteurs, state):
    vlm = FakeVLM(classif("piece_identite"))
    out = await analyser(state, images, resultats, vlm, extracteurs)
    assert out["image_status"] == m.Status.EXPECTED_TYPE.value
    assert "ordonnance" in out["image_instruction"]
    assert "piece_identite" in out["image_instruction"]
    assert resultats.recus == []


async def test_description_de_l_image_n_atteint_pas_la_consigne(
    images, resultats, extracteurs, state
):
    vlm = FakeVLM(classif("autre", description=INJECTION))
    out = await analyser(
        {**state, "expected_image_type": None}, images, resultats, vlm, extracteurs
    )
    assert out["image_status"] == m.Status.OTHER.value
    assert INJECTION not in repr(out)


async def test_l_outil_met_la_consigne_dans_le_toolmessage(
    images, resultats, extracteurs, state
):
    outil = m.creer_outil_image(images, resultats, FakeVLM(classif()), extracteurs)
    cmd = await outil.coroutine(state=state, tool_call_id="c1")
    assert "image_instruction" not in cmd.update
    assert cmd.update["messages"][0].content == m.MESSAGES[m.Status.EXTRACTED]
    assert cmd.update["messages"][0].tool_call_id == "c1"