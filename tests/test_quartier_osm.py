from typing import Any

import pytest

from agent.modules.lieux.osm_parse import (
    QuartierOsm,
    extraire_quartiers,
    fusionner_quartiers_osm,
    normaliser_nom,
    retirer_prefixe_q,
)


def _q(osm_ref: str, nom: str) -> QuartierOsm:
    return QuartierOsm(
        osm_ref=osm_ref,
        name=nom,
        name_norm=normaliser_nom(nom),
        place_type="suburb",
        lat=12.37,
        lng=-1.52,
    )


def _feature(osm_ref: str, nom: str, place: str = "suburb") -> dict[str, Any]:
    return {
        "id": osm_ref,
        "properties": {"place": place, "name": nom},
        "geometry": {"type": "Point", "coordinates": [-1.52, 12.37]},
    }


@pytest.mark.parametrize(
    ("entree", "attendu"),
    [
        ("Q-Dapoya", "Dapoya"),
        ("Q Tebedogo", "Tebedogo"),
        ("q-Gounghin", "Gounghin"),
        ("Q - Ipala", "Ipala"),
        ("  Q-Dapoya  ", "Dapoya"),
        ("Dapoya", "Dapoya"),
        ("Quartier Dapoya", "Quartier Dapoya"),
        ("Q", "Q"),
        ("Q-", "Q-"),
        ("Dapoya Q", "Dapoya Q"),
    ],
)
def test_retirer_prefixe_q(entree: str, attendu: str) -> None:
    assert retirer_prefixe_q(entree) == attendu


def test_fusion_garde_le_plus_petit_osm_ref() -> None:
    osm = [_q("n99", "Natenga"), _q("a12", "Natenga"), _q("n5", "Ipala")]
    assert {q.osm_ref for q in fusionner_quartiers_osm(osm)} == {"a12", "n5"}


def test_fusion_deterministe_quel_que_soit_l_ordre() -> None:
    osm = [_q("n7", "Silmissin"), _q("a3", "Silmissin"), _q("w1", "Silmissin")]
    assert fusionner_quartiers_osm(osm) == fusionner_quartiers_osm(list(reversed(osm)))
    assert fusionner_quartiers_osm(osm)[0].osm_ref == "a3"


def test_fusion_sans_doublon_garde_tout() -> None:
    osm = [_q("n1", "Dapoya"), _q("n2", "Gounghin")]
    assert len(fusionner_quartiers_osm(osm)) == 2


def test_fusion_liste_vide() -> None:
    assert fusionner_quartiers_osm([]) == []


def test_extraire_retire_le_prefixe_du_nom_et_du_name_norm() -> None:
    quartiers = extraire_quartiers([_feature("n1", "Q-Dapoya")])
    assert [(q.name, q.name_norm) for q in quartiers] == [("Dapoya", "dapoya")]


def test_extraire_fusionne_les_variantes_avec_et_sans_prefixe() -> None:
    features = [
        _feature("n10", "Q Ipala"),
        _feature("a2", "Q-Ipala"),
        _feature("n3", "Silmissin"),
        _feature("n4", "Q-Silmissin"),
    ]
    resultat = {q.name_norm: q.osm_ref for q in extraire_quartiers(features)}
    assert resultat == {"ipala": "a2", "silmissin": "n3"}


def test_extraire_accepte_village_hamlet_town() -> None:
    features = [
        _feature("n1", "Kossodo", "village"),
        _feature("n2", "Pissy", "hamlet"),
        _feature("n3", "Tanghin", "town"),
        _feature("n4", "Ailleurs", "city"),
    ]
    assert {q.name for q in extraire_quartiers(features)} == {"Kossodo", "Pissy", "Tanghin"}


def test_extraire_ignore_les_noms_vides() -> None:
    assert extraire_quartiers([_feature("n1", "  "), _feature("n2", "")]) == []
