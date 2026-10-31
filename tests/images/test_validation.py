import json
import logging

import pytest

from agent.core.prompt import PIECE_IDENTITE_PROMPT
from agent.modules.images.extracteurs import valider_piece_identite
from agent.modules.images.image_data import (
    MAX_BRUT,
    Accepte,
    IdCardFields,
    Ordonnance_output,
    ReasonRejet,
    Reject,
    parse_modele,
)
from agent.modules.images.normalisation import valider_ordonnance

SECRET = "ZZSECRETZZ"


def ordonnance(**surcharge) -> str:
    base = {
        "type": "ordonnance",
        "lisibilite": "bonne",
        "lignes": [{"text": "Paracétamol 500 mg 1 cp matin", "confident": "haute"}],
        "medicaments_ecrits": [{"text": "Paracétamol 500 mg", "confident": "haute"}],
        "signe_medical_visible": False,
    }
    return json.dumps({**base, **surcharge})


def champ(valeur, certitude="haute") -> dict:
    return {"value": valeur, "confident": certitude}


def piece(**surcharge) -> str:
    base = {
        "field_name": champ(SECRET),
        "born_on": champ("01/01/1990"),
        "identity_ID": champ("B1234567"),
    }
    return json.dumps({**base, **surcharge})


def rejet(res, raison, retryable):
    assert isinstance(res, Reject)
    assert res.reason == raison
    assert res.retryable is retryable


# ---------- parse_modele ----------


def test_parse_nominal():
    assert isinstance(parse_modele(ordonnance(), Ordonnance_output), Ordonnance_output)


def test_parse_accepte_les_balises_markdown():
    brut = f"```json\n{ordonnance()}\n```"
    assert isinstance(parse_modele(brut, Ordonnance_output), Ordonnance_output)


def test_parse_taille_excessive():
    rejet(parse_modele("x" * (MAX_BRUT + 1), Ordonnance_output), ReasonRejet.TAILLE_EXCESSIVE, True)


def test_parse_a_la_limite_la_taille_est_acceptee():
    # exactement MAX_BRUT : pas de rejet de taille, mais pas du JSON
    rejet(parse_modele("x" * MAX_BRUT, Ordonnance_output), ReasonRejet.JSON_INVALIDE, True)


@pytest.mark.parametrize("brut", ["pas du json", "", "{", "{'a': 1}"])
def test_parse_json_invalide(brut):
    rejet(parse_modele(brut, Ordonnance_output), ReasonRejet.JSON_INVALIDE, True)


def test_parse_json_qui_n_est_pas_un_objet():
    rejet(parse_modele("[1, 2]", Ordonnance_output), ReasonRejet.SCHEMA_INVALIDE, True)


def test_parse_cle_en_trop_est_interdite_et_non_reessayable():
    rejet(parse_modele(ordonnance(prix=3), Ordonnance_output), ReasonRejet.CHAMP_INTERDIT, False)


def test_parse_champ_interdit_prime_sur_les_autres_erreurs():
    brut = ordonnance(prix=3, lisibilite="n'importe quoi")
    rejet(parse_modele(brut, Ordonnance_output), ReasonRejet.CHAMP_INTERDIT, False)


def test_parse_texte_trop_long():
    lignes = [{"text": "a" * 301, "confident": "haute"}]
    rejet(
        parse_modele(ordonnance(lignes=lignes), Ordonnance_output),
        ReasonRejet.TAILLE_EXCESSIVE,
        True,
    )


@pytest.mark.parametrize(
    "surcharge",
    [
        {"lisibilite": "moyenne"},  # hors Literal
        {"type": "autre"},
        {"lignes": [{"text": "", "confident": "haute"}]},  # texte vide
        {"lignes": [{"text": "[illisible]", "confident": "haute"}]},  # illisible => basse
        {"medicaments_ecrits": [{"text": "x"}]},  # certitude absente
    ],
)
def test_parse_schema_invalide(surcharge):
    rejet(
        parse_modele(ordonnance(**surcharge), Ordonnance_output), ReasonRejet.SCHEMA_INVALIDE, True
    )


def test_parse_ne_journalise_jamais_le_contenu(caplog):
    caplog.set_level(logging.DEBUG)
    lignes = [{"text": SECRET, "confident": "inconnue"}]
    parse_modele(ordonnance(lignes=lignes), Ordonnance_output)
    assert caplog.records and SECRET not in caplog.text


# ---------- valider_ordonnance ----------


def test_ordonnance_nominale():
    res = valider_ordonnance(ordonnance())
    assert isinstance(res, Accepte) and res.output.type == "ordonnance"


def test_ordonnance_acceptee_ne_fuit_pas_dans_le_repr():
    res = valider_ordonnance(ordonnance())
    assert "Paracétamol" not in repr(res)


def test_ordonnance_signe_medical():
    rejet(
        valider_ordonnance(ordonnance(signe_medical_visible=True)), ReasonRejet.SIGNE_MEDICAL, False
    )


def test_signe_medical_prime_sur_medicament_absent():
    meds = [{"text": "Inconnu 9 mg", "confident": "haute"}]
    rejet(
        valider_ordonnance(ordonnance(signe_medical_visible=True, medicaments_ecrits=meds)),
        ReasonRejet.SIGNE_MEDICAL,
        False,
    )


def test_ordonnance_medicament_absent_des_lignes():
    meds = [{"text": "Amoxicilline 1 g", "confident": "haute"}]
    rejet(
        valider_ordonnance(ordonnance(medicaments_ecrits=meds)), ReasonRejet.MEDICAMENT_ABSENT, True
    )


def test_ordonnance_un_seul_medicament_absent_suffit_a_rejeter():
    meds = [
        {"text": "Paracétamol 500 mg", "confident": "haute"},
        {"text": "Amoxicilline 1 g", "confident": "haute"},
    ]
    rejet(
        valider_ordonnance(ordonnance(medicaments_ecrits=meds)), ReasonRejet.MEDICAMENT_ABSENT, True
    )


def test_ordonnance_medicaments_sans_lignes_sont_rejetes():
    rejet(valider_ordonnance(ordonnance(lignes=[])), ReasonRejet.MEDICAMENT_ABSENT, True)


def test_ordonnance_sans_medicament_est_acceptee():
    assert isinstance(valider_ordonnance(ordonnance(medicaments_ecrits=[])), Accepte)


@pytest.mark.parametrize("texte", ["[illisible]", "Para[illisible] 500"])
def test_ordonnance_medicament_illisible_est_exempte(texte):
    meds = [{"text": texte, "confident": "basse"}]
    res = valider_ordonnance(ordonnance(lignes=[], medicaments_ecrits=meds))
    assert isinstance(res, Accepte)


def test_ordonnance_tolere_accents_casse_et_ordre():
    meds = [{"text": "500 MG paracetamol", "confident": "haute"}]
    assert isinstance(valider_ordonnance(ordonnance(medicaments_ecrits=meds)), Accepte)


def test_ordonnance_transmet_les_rejets_de_parse():
    rejet(valider_ordonnance("pas du json"), ReasonRejet.JSON_INVALIDE, True)
    rejet(valider_ordonnance(ordonnance(prix=3)), ReasonRejet.CHAMP_INTERDIT, False)


def test_medicament_absent_ne_journalise_pas_le_texte(caplog):
    caplog.set_level(logging.DEBUG)
    meds = [{"text": SECRET, "confident": "haute"}]
    valider_ordonnance(ordonnance(medicaments_ecrits=meds))
    assert caplog.records and SECRET not in caplog.text


# ---------- valider_piece_identite ----------


def test_piece_nominale_et_champs_omis_valent_none():
    res = valider_piece_identite(piece())
    assert isinstance(res, Accepte) and isinstance(res.output, IdCardFields)
    assert res.output.field_name.value == SECRET
    assert res.output.country.value is None and res.output.country.confident is None


def test_piece_acceptee_ne_fuit_pas_dans_le_repr():
    assert SECRET not in repr(valider_piece_identite(piece()))


def test_piece_cle_inconnue_au_niveau_superieur():
    rejet(valider_piece_identite(piece(adresse=champ("x"))), ReasonRejet.CHAMP_INTERDIT, False)


def test_piece_cle_inconnue_dans_un_champ_est_ignoree():
    # décision de la session 5 : Extracted_field n'est pas en extra="forbid"
    brut = piece(born_on={"value": "01/01/1990", "confident": "haute", "x": 1})
    assert isinstance(valider_piece_identite(brut), Accepte)


def test_piece_illisible_exige_certitude_basse():
    rejet(
        valider_piece_identite(piece(sexe=champ("[illisible]", "haute"))),
        ReasonRejet.SCHEMA_INVALIDE,
        True,
    )
    assert isinstance(valider_piece_identite(piece(sexe=champ("[illisible]", "basse"))), Accepte)


def test_piece_illisible_seulement_si_valeur_exacte():
    # règle `==` pour Extracted_field (contrairement à `in` pour Drug)
    assert isinstance(valider_piece_identite(piece(sexe=champ("x [illisible]", "haute"))), Accepte)


def test_piece_json_invalide():
    rejet(valider_piece_identite("nope"), ReasonRejet.JSON_INVALIDE, True)


def test_le_prompt_et_le_schema_ont_les_memes_champs():
    for nom in IdCardFields.model_fields:
        assert nom in PIECE_IDENTITE_PROMPT
