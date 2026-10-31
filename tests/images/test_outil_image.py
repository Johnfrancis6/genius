from typing import get_type_hints

import pytest

from agent.conversation.state import ConversationState  # à adapter
from agent.modules.images import image_tool as m

from .fakes import (
    INJECTION,
    SECRET,
    FakeImageStore,
    FakeResultStore,
    FakeVLM,
    classif,
)

CLES_ETAT = {"image_status", "image_type_detected", "image_result_id", "pending_image_id"}


async def appeler(outil, state, call_id="call_1"):
    # on appelle la coroutine sous-jacente : pas besoin d'un ToolNode
    return await outil.coroutine(state=state, tool_call_id=call_id)


def fabriquer(images, resultats, vlm, extracteurs):
    return m.creer_outil_image(images, resultats, vlm, extracteurs)


def test_les_cles_ecrites_existent_dans_l_etat():
    assert CLES_ETAT <= set(get_type_hints(ConversationState))


async def test_contrat_des_cles_mises_a_jour(images, resultats, extracteurs, state):
    outil = fabriquer(images, resultats, FakeVLM(classif()), extracteurs)
    cmd = await appeler(outil, state)
    assert set(cmd.update) == CLES_ETAT | {"messages"}


@pytest.mark.parametrize("retire", ["user_id", "pending_image_id"])
async def test_etat_incomplet(retire, images, resultats, extracteurs, state):
    vlm = FakeVLM(classif())
    state = {k: v for k, v in state.items() if k != retire}
    cmd = await appeler(fabriquer(images, resultats, vlm, extracteurs), state)
    assert cmd.update["image_status"] == m.Status.NO_IMAGE.value
    assert cmd.update["pending_image_id"] is None and vlm.appels == []
    assert cmd.update["messages"][0].tool_call_id == "call_1"


async def test_image_absente_du_magasin(resultats, extracteurs, state):
    vlm = FakeVLM(classif())
    cmd = await appeler(fabriquer(FakeImageStore(), resultats, vlm, extracteurs), state)
    assert cmd.update["image_status"] == m.Status.TECHNICAL_ERROR.value
    assert vlm.appels == []


async def test_extraction_reussie(images, resultats, extracteurs, state):
    cmd = await appeler(fabriquer(images, resultats, FakeVLM(classif()), extracteurs), state)
    u = cmd.update
    assert u["image_status"] == m.Status.EXTRACTED.value
    assert u["image_type_detected"] == "ordonnance" and u["image_result_id"] == "res-1"
    assert len(resultats.recus) == 1 and images.supprimees == [("u1", "img1")]
    assert SECRET not in repr(u)  # les données ne vont pas à l'agent


async def test_signe_medical(images, resultats, extracteurs, state):
    cmd = await appeler(
        fabriquer(images, resultats, FakeVLM(classif(signe=True)), extracteurs), state
    )
    assert cmd.update["image_status"] == m.Status.MEDICAL_SIGN.value
    assert cmd.update["image_result_id"] is None
    assert all(e.appels == 0 for e in extracteurs.values())
    assert images.supprimees == [("u1", "img1")]


@pytest.mark.parametrize("magasin", ["images_get", "resultats_put"])
async def test_exception_interne(magasin, extracteurs, state):
    images = FakeImageStore({("u1", "img1"): b"x"}, echec_get=magasin == "images_get")
    resultats = FakeResultStore(echec_put=magasin == "resultats_put")
    cmd = await appeler(fabriquer(images, resultats, FakeVLM(classif()), extracteurs), state)
    assert cmd.update["image_status"] == m.Status.TECHNICAL_ERROR.value
    assert cmd.update["image_result_id"] is None
    assert images.supprimees == [("u1", "img1")]


async def test_l_image_est_supprimee_meme_apres_une_erreur(resultats, extracteurs, state):
    images = FakeImageStore({("u1", "img1"): b"x"})
    await appeler(
        fabriquer(images, FakeResultStore(echec_put=True), FakeVLM(classif()), extracteurs), state
    )
    assert images.supprimees == [("u1", "img1")]


async def test_echec_de_suppression_ne_masque_pas_le_resultat(resultats, extracteurs, state):
    images = FakeImageStore({("u1", "img1"): b"x"}, echec_delete=True)
    cmd = await appeler(fabriquer(images, resultats, FakeVLM(classif()), extracteurs), state)
    assert cmd.update["image_status"] == m.Status.EXTRACTED.value


async def test_description_issue_de_l_image_n_atteint_pas_l_agent(
    images, resultats, extracteurs, state
):
    vlm = FakeVLM(classif("autre", description=INJECTION))
    cmd = await appeler(
        fabriquer(images, resultats, vlm, extracteurs), {**state, "expected_image_type": None}
    )
    assert cmd.update["image_status"] == m.Status.OTHER.value
    assert INJECTION not in repr(cmd.update)


async def test_type_attendu_hors_liste_est_ignore(images, resultats, extracteurs, state):
    vlm = FakeVLM(classif("piece_identite"))
    cmd = await appeler(
        fabriquer(images, resultats, vlm, extracteurs), {**state, "expected_image_type": "admin"}
    )
    assert cmd.update["image_status"] == m.Status.TYPE_TO_CONFIRM.value
    assert all(e.appels == 0 for e in extracteurs.values())


@pytest.mark.parametrize("statut", list(m.Status))
def test_chaque_statut_a_un_texte(statut):
    r = m.AnalyseResult(statut, type_detected="ordonnance", type_expected="ordonnance")
    assert m._texte(r).strip()


def test_le_texte_n_utilise_jamais_la_description():
    r = m.AnalyseResult(m.Status.OTHER, description=INJECTION)
    assert INJECTION not in m._texte(r)
