import pytest

from agent.modules.lieux.recherche import (
    _Candidat,
    classer,
    construire_libelle,
    type_de_recherche,
)


def _c(osm_ref: str, nom: str, lat: float, lng: float, quartier: str | None = None) -> _Candidat:
    return _Candidat(osm_ref, "health_center", nom, lat, lng, quartier, None, None)


@pytest.mark.parametrize(
    ("kind", "attendu"),
    [
        ("pharmacie", ("pharmacy", False)),
        ("Pharmacie de garde", ("pharmacy", True)),
        ("garde", ("pharmacy", True)),
        ("PHARMACIES", ("pharmacy", False)),
        ("centre de santé", ("health_center", False)),
        ("clinique", ("health_center", False)),
        ("CSPS", ("health_center", False)),
        ("", (None, False)),
        ("   ", (None, False)),
        (None, (None, False)),
        (42, (None, False)),
    ],
)
def test_type_de_recherche(kind: object, attendu: tuple[str | None, bool]) -> None:
    assert type_de_recherche(kind) == attendu


@pytest.mark.parametrize(
    ("nom", "quartier", "attendu"),
    [
        ("CSPS", "Dapoya", "CSPS (Dapoya)"),
        ("Maternité", "Dapoya", "Maternité (Dapoya)"),
        ("Pharmacie", "Zogona", "Pharmacie (Zogona)"),
        ("CSPS", None, "CSPS"),
        ("CSPS de Dapoya", "Dapoya", "CSPS de Dapoya"),
        ("Pharmacie Camille", "Dapoya", "Pharmacie Camille"),
    ],
)
def test_construire_libelle(nom: str, quartier: str | None, attendu: str) -> None:
    assert construire_libelle(nom, quartier) == attendu


def test_classer_trie_par_distance_et_garde_trois() -> None:
    candidats = [
        _c("n4", "Loin", 12.40, -1.50),
        _c("n1", "Proche", 12.3701, -1.5201),
        _c("n3", "Moyen2", 12.38, -1.52),
        _c("n2", "Moyen1", 12.375, -1.52),
    ]
    lieux = classer(candidats, 12.37, -1.52)
    assert [lieu.osm_ref for lieu in lieux] == ["n1", "n2", "n3"]
    assert lieux[0].distance_m < lieux[1].distance_m < lieux[2].distance_m
    assert 0 < lieux[0].distance_m < 30


def test_classer_departage_les_egalites_par_osm_ref() -> None:
    candidats = [_c("n9", "B", 12.38, -1.52), _c("a1", "A", 12.38, -1.52)]
    assert [lieu.osm_ref for lieu in classer(candidats, 12.37, -1.52)] == ["a1", "n9"]


def test_classer_moins_de_trois_et_liste_vide() -> None:
    assert classer([], 12.37, -1.52) == []
    assert len(classer([_c("n1", "A", 12.38, -1.52)], 12.37, -1.52)) == 1


def test_classer_reprend_quartier_telephone_horaires() -> None:
    candidat = _Candidat("n1", "pharmacy", "Pharmacie", 12.38, -1.52, "Dapoya", "+226 1", "24h/24")
    (lieu,) = classer([candidat], 12.37, -1.52)
    assert (lieu.label, lieu.quartier, lieu.phone, lieu.hours_text) == (
        "Pharmacie (Dapoya)",
        "Dapoya",
        "+226 1",
        "24h/24",
    )