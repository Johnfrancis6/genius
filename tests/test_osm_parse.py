import json

import pytest

from agent.modules.lieux.osm_parse import (
    LieuOsm,
    QuartierOsm,
    centre,
    classer,
    distance_m,
    extraire_lieux,
    extraire_quartiers,
    lire_features,
    marquer_doublons,
    normaliser_nom,
    quartier_proche,
)

LAT, LNG = 12.37, -1.52
D_100M = 0.0009  # degrés de latitude, environ 100 m
D_300M = 0.0027  # environ 300 m


def _lieu(ref, kind="pharmacy", name="Pharmacie Camille", dlat=0.0, polygone=False):
    return LieuOsm(
        osm_ref=ref,
        kind=kind,
        name=name,
        osm_tag=kind,
        lat=LAT + dlat,
        lng=LNG,
        is_polygon=polygone,
    )


def _quartier(ref, lat, lng=LNG):
    return QuartierOsm(osm_ref=ref, name=ref, name_norm=ref, place_type="quarter", lat=lat, lng=lng)


@pytest.mark.parametrize(
    ("props", "attendu"),
    [
        ({"amenity": "pharmacy"}, "pharmacy"),
        ({"healthcare": "pharmacy"}, "pharmacy"),
        ({"amenity": "pharmacy", "healthcare": "pharmacy"}, "pharmacy"),
        ({"amenity": "hospital"}, "health_center"),
        ({"amenity": "clinic"}, "health_center"),
        ({"amenity": "doctors"}, "health_center"),
        ({"healthcare": "centre"}, "health_center"),
        ({"healthcare": "doctor"}, "health_center"),
        ({"healthcare": "birthing_centre"}, "health_center"),
        ({"amenity": "dentist"}, None),
        ({"healthcare": "laboratory"}, None),
        ({"healthcare": "hospice"}, None),
        ({"healthcare": "rehabilitation"}, None),
        ({"amenity": "veterinary"}, None),
        ({"healthcare": "alternative"}, None),
        ({"healthcare": "yes"}, None),
        ({}, None),
    ],
)
def test_classer(props, attendu):
    assert classer(props) == attendu


def test_normaliser_nom_casse_accents_espaces():
    assert normaliser_nom("  Pharmacie   CAMILLE ") == "pharmacie camille"
    assert normaliser_nom("Maternité de Pogbi") == "maternite de pogbi"


def test_normaliser_nom_apostrophes_unifiees():
    reference = normaliser_nom("Pharmacie de l'avenir")
    assert normaliser_nom("Pharmacie de l´avenir") == reference
    assert normaliser_nom("Pharmacie de l’avenir") == reference


def test_centre_point_ordre_lat_lng():
    assert centre({"type": "Point", "coordinates": [-1.5, 12.3]}) == (12.3, -1.5)


def test_centre_multipolygone_carre():
    anneau = [[-1.51, 12.30], [-1.49, 12.30], [-1.49, 12.32], [-1.51, 12.32], [-1.51, 12.30]]
    lat, lng = centre({"type": "MultiPolygon", "coordinates": [[anneau]]})
    assert lat == pytest.approx(12.31)
    assert lng == pytest.approx(-1.50)
    lat, lng = centre({"type": "Polygon", "coordinates": [anneau]})
    assert (lat, lng) == (pytest.approx(12.31), pytest.approx(-1.50))


def test_centre_geometrie_non_geree():
    with pytest.raises(ValueError):
        centre({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})


def test_distance_150_m():
    assert distance_m(12.0, -1.5, 12.00135, -1.5) == pytest.approx(150, abs=2)
    assert distance_m(12.0, -1.5, 12.0, -1.5) == 0


def test_quartier_proche_choisit_le_plus_proche():
    q1, q2 = _quartier("q1", LAT), _quartier("q2", LAT + 0.03)
    assert quartier_proche(LAT + 0.001, LNG, [q1, q2]) == q1
    assert quartier_proche(LAT + 0.029, LNG, [q1, q2]) == q2


def test_quartier_proche_au_dela_de_3_km():
    assert quartier_proche(LAT + 0.03, LNG, [_quartier("q1", LAT)]) is None
    assert quartier_proche(LAT, LNG, []) is None


def test_doublons_polygone_prefere_au_point():
    point = _lieu("n1", name="Clinique Suka", kind="health_center")
    polygone = _lieu("a2", name="Clinique Suka", kind="health_center", dlat=D_100M, polygone=True)
    assert marquer_doublons([point, polygone]) == {"n1": "a2"}


def test_doublons_egalite_le_plus_petit_ref():
    assert marquer_doublons([_lieu("n2"), _lieu("n1")]) == {"n2": "n1"}


def test_doublons_chaine_de_trois_vers_un_seul_garde():
    lieux = [
        _lieu("n3", name="pharmacie Camille"),
        _lieu("n1", name="Pharmacie Camille"),
        _lieu("n2", name="Pharmacie Camille", dlat=D_100M),
    ]
    assert marquer_doublons(lieux) == {"n2": "n1", "n3": "n1"}


def test_doublons_kind_different_non_fusionne():
    lieux = [_lieu("n1", kind="pharmacy"), _lieu("n2", kind="health_center")]
    assert marquer_doublons(lieux) == {}


def test_doublons_sans_nom_non_fusionne():
    assert marquer_doublons([_lieu("n1", name=None), _lieu("n2", name=None)]) == {}


def test_doublons_au_dela_de_150_m_non_fusionne():
    assert marquer_doublons([_lieu("n1"), _lieu("n2", dlat=D_300M)]) == {}


def test_lire_features_separateur_et_lignes_vides(tmp_path):
    fichier = tmp_path / "lieux.geojsonseq"
    feature = {"type": "Feature", "id": "n1", "geometry": None, "properties": {}}
    fichier.write_text("\x1e" + json.dumps(feature) + "\n\n" + json.dumps(feature) + "\n")
    assert [f["id"] for f in lire_features(fichier)] == ["n1", "n1"]


def _point(ref, props, lng=LNG, lat=LAT):
    return {
        "type": "Feature",
        "id": ref,
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": props,
    }


def test_extraire_lieux_filtre_et_champs():
    carre = [[-1.51, 12.30], [-1.49, 12.30], [-1.49, 12.32], [-1.51, 12.32], [-1.51, 12.30]]
    features = [
        _point("n322806278", {"amenity": "pharmacy", "name": "Pharmacie de l´avenir"}),
        _point("n2", {"amenity": "hospital"}),
        _point("n3", {"amenity": "dentist", "name": "Dentiste"}),
        {"type": "Feature", "id": "w4", "geometry": {"type": "LineString", "coordinates": []}},
        {
            "type": "Feature",
            "id": "a5",
            "geometry": {"type": "MultiPolygon", "coordinates": [[carre]]},
            "properties": {"amenity": "clinic", "name": "Clinique FRANY"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"amenity": "pharmacy", "name": "Sans identifiant"},
        },
    ]
    par_ref = {lieu.osm_ref: lieu for lieu in extraire_lieux(features)}
    assert set(par_ref) == {"n322806278", "n2", "a5"}
    assert par_ref["n322806278"].kind == "pharmacy"
    assert par_ref["n2"].name is None
    assert par_ref["a5"].is_polygon is True
    assert par_ref["a5"].lat == pytest.approx(12.31)


def test_extraire_quartiers():
    features = [
        _point("n1", {"place": "quarter", "name": "Dassasgho"}),
        _point("n2", {"place": "suburb", "name": ""}),
        _point("n3", {"place": "city", "name": "Ouagadougou"}),
        _point("n4", {"amenity": "pharmacy", "name": "Pharmacie"}),
    ]
    quartiers = extraire_quartiers(features)
    assert [q.osm_ref for q in quartiers] == ["n1"]
    assert quartiers[0].name_norm == "dassasgho"
    assert quartiers[0].place_type == "quarter"