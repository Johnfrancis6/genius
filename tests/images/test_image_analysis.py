import pytest

from agent.modules.images import image_tool as m
from agent.modules.images.image_data import Accepte, ReasonRejet, Reject

from .fakes import INJECTION, SECRET, FakeExtracteur, FakeVLM, SlowVLM, classif


async def lancer(vlm, expected, extracteurs):
    return await m.image_analysis(b"img", expected, vlm, extracteurs)


def aucun_appel(extracteurs):
    return all(e.appels == 0 for e in extracteurs.values())


@pytest.mark.parametrize("type_", ["ordonnance", "piece_identite", "autre", "illisible"])
async def test_signe_medical_arrete_tout(type_, extracteurs):
    r = await lancer(FakeVLM(classif(type_, signe=True)), None, extracteurs)
    assert r.status == m.Status.MEDICAL_SIGN
    assert aucun_appel(extracteurs) and r.data is None


@pytest.mark.parametrize("reponse", [classif("illisible"), classif("ordonnance", "mauvaise")])
async def test_image_inutilisable(reponse, extracteurs):
    r = await lancer(FakeVLM(reponse), None, extracteurs)
    assert r.status == m.Status.IMAGE_TO_RESEND and aucun_appel(extracteurs)


async def test_type_inattendu(extracteurs):
    r = await lancer(FakeVLM(classif("piece_identite")), "ordonnance", extracteurs)
    assert r.status == m.Status.EXPECTED_TYPE
    assert (r.type_detected, r.type_expected) == ("piece_identite", "ordonnance")
    assert aucun_appel(extracteurs)


async def test_piece_sans_type_attendu_n_est_pas_lue(extracteurs):
    r = await lancer(FakeVLM(classif("piece_identite")), None, extracteurs)
    assert r.status == m.Status.TYPE_TO_CONFIRM and aucun_appel(extracteurs)


async def test_ordonnance_sans_type_attendu_est_extraite(extracteurs):
    r = await lancer(FakeVLM(classif("ordonnance")), None, extracteurs)
    assert r.status == m.Status.EXTRACTED
    assert extracteurs["ordonnance"].appels == 1
    assert extracteurs["piece_identite"].appels == 0


async def test_type_autre(extracteurs):
    r = await lancer(FakeVLM(classif("autre", description="un chat")), None, extracteurs)
    assert r.status == m.Status.OTHER and r.description == "un chat"


async def test_autre_alors_qu_un_type_est_attendu(extracteurs):
    r = await lancer(FakeVLM(classif("autre")), "ordonnance", extracteurs)
    assert r.status == m.Status.EXPECTED_TYPE


async def test_classification_rejetee_deux_tentatives(extracteurs):
    vlm = FakeVLM("pas du json")
    r = await lancer(vlm, None, extracteurs)
    assert r.status == m.Status.TECHNICAL_ERROR and len(vlm.appels) == 2
    assert aucun_appel(extracteurs)


async def test_erreur_fournisseur_a_la_classification(extracteurs):
    r = await lancer(FakeVLM(RuntimeError("503")), None, extracteurs)
    assert r.status == m.Status.TECHNICAL_ERROR
    assert r.reason == ReasonRejet.ERREUR_FOURNISSEUR


async def test_extracteur_absent():
    r = await lancer(FakeVLM(classif("ordonnance")), None, {})
    assert r.status == m.Status.TECHNICAL_ERROR


async def test_extraction_rejetee_par_le_fournisseur():
    ext = {"ordonnance": FakeExtracteur(Reject(ReasonRejet.ERREUR_FOURNISSEUR))}
    r = await lancer(FakeVLM(classif("ordonnance")), None, ext)
    assert r.status == m.Status.TECHNICAL_ERROR


async def test_extraction_rejetee_pour_schema_invalide():
    # décision session 5 : tout Reject d'extraction => TECHNICAL_ERROR
    ext = {"ordonnance": FakeExtracteur(Reject(ReasonRejet.SCHEMA_INVALIDE, retryable=True))}
    r = await lancer(FakeVLM(classif("ordonnance")), None, ext)
    assert r.status == m.Status.TECHNICAL_ERROR and r.data is None
    assert r.reason == ReasonRejet.SCHEMA_INVALIDE


async def test_timeout(monkeypatch, extracteurs):
    monkeypatch.setattr(m, "TIMEOUT_S", 0.05)
    r = await lancer(SlowVLM(), None, extracteurs)
    assert r.status == m.Status.TECHNICAL_ERROR
    assert r.reason == ReasonRejet.ERREUR_FOURNISSEUR


async def test_repr_ne_montre_ni_donnees_ni_description(extracteurs):
    ext = {"ordonnance": FakeExtracteur(Accepte(type("S", (), {"secret": SECRET})()))}
    r1 = await lancer(FakeVLM(classif("ordonnance")), None, ext)
    r2 = await lancer(FakeVLM(classif("autre", description=INJECTION)), None, extracteurs)
    assert SECRET not in repr(r1) and INJECTION not in repr(r2)
