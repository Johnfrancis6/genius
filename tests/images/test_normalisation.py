import pytest

from agent.modules.images.image_data import Drug
from agent.modules.images.normalisation import _present, mots, normaliser


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("Paracétamol 500 mg", "paracetamol 500 mg"),
        ("PARACÉTAMOL", "paracetamol"),
        ("  Amoxicilline \t\n 500mg  ", "amoxicilline 500 mg"),
        ("500mg", "500 mg"),                       # chiffre puis lettre
        ("mg500", "mg 500"),                       # lettre puis chiffre
        ("Paracétamol500MG", "paracetamol 500 mg"),
        ("Amox-Clav 1g/125mg", "amox clav 1 g 125 mg"),
        ("Vit_C, 1000mg.", "vit c 1000 mg"),       # "_" et ponctuation -> espace
        ("[illisible]", "illisible"),
        ("Αλφα1", "αλφα 1"),                       # lettres non latines conservées
        ("５００ｍｇ", "500 mg"),                     # NFKD : pleine chasse -> ASCII
        ("...---", ""),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normaliser(brut, attendu):
    assert normaliser(brut) == attendu


def test_les_accents_precomposes_et_combines_sont_equivalents():
    assert normaliser("é") == normaliser("e\u0301") == "e"


@pytest.mark.parametrize(
    "brut",
    ["Paracétamol500MG", "Amox-Clav 1g/125mg", "  ÉCOLE  ", "...", "500mg"],
)
def test_normaliser_est_idempotent(brut):
    une_fois = normaliser(brut)
    assert normaliser(une_fois) == une_fois


def test_mots_renvoie_un_frozenset_de_mots_normalises():
    r = mots("Paracétamol 500mg")
    assert isinstance(r, frozenset)
    assert r == {"paracetamol", "500", "mg"}


def test_mots_ignore_l_ordre_et_les_doublons():
    assert mots("b a a") == mots("a b") == {"a", "b"}


def test_mots_vide_pour_une_ponctuation_seule():
    assert mots("...") == frozenset()


# ---- _present : dépend directement de la normalisation ----

def drug(texte: str) -> Drug:
    return Drug(text=texte, confident="haute")


LIGNES = [drug("Paracétamol 500mg, 1 cp matin et soir"), drug("Amoxicilline 1 g")]


def test_present_malgre_accents_casse_et_collage():
    assert _present(drug("PARACETAMOL 500 mg"), LIGNES)


def test_present_ordre_libre():
    assert _present(drug("mg 500 paracetamol"), LIGNES)


def test_absent_si_un_mot_manque():
    assert not _present(drug("Paracétamol 1000 mg"), LIGNES)


def test_absent_si_les_mots_sont_repartis_sur_deux_lignes():
    lignes = [drug("Paracétamol"), drug("500 mg")]
    assert not _present(drug("Paracétamol 500 mg"), lignes)


def test_absent_si_le_texte_se_reduit_a_de_la_ponctuation():
    assert not _present(drug("..."), LIGNES)


def test_absent_si_aucune_ligne():
    assert not _present(drug("Paracétamol"), [])