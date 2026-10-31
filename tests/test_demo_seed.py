from typing import get_args

import pytest

from agent.conversation.state import Situation
from agent.modules.demo.pharmacies import (
    PharmacieDemo,
    trier_par_distance,
)
from agent.modules.demo.produits import PRODUITS_DEMO, normaliser_produit
from agent.modules.demo.seed import generer_agents, generer_stock


def _pharmacies(n: int = 6) -> list[PharmacieDemo]:
    return [PharmacieDemo(f"n{i}", f"Pharmacie {i}", 12.37 + i * 0.001, -1.60) for i in range(n)]


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("Artéméther-Luméfantrine", "artemether lumefantrine"),
        ("  PARACÉTAMOL ", "paracetamol"),
        ("sels  de réhydratation", "sels de rehydratation"),
        ("Vitamine C", "vitamine c"),
    ],
)
def test_normaliser_produit(brut: str, attendu: str) -> None:
    assert normaliser_produit(brut) == attendu


def test_produits_sans_dose() -> None:
    assert not any(c.isdigit() for p in PRODUITS_DEMO for c in p)


def test_stock_reproductible() -> None:
    a = generer_stock(_pharmacies(), PRODUITS_DEMO, 1, "amoxicilline")
    b = generer_stock(_pharmacies(), PRODUITS_DEMO, 1, "amoxicilline")
    assert a == b


def test_stock_change_avec_la_graine() -> None:
    a = generer_stock(_pharmacies(), PRODUITS_DEMO, 1, "amoxicilline")
    b = generer_stock(_pharmacies(), PRODUITS_DEMO, 2, "amoxicilline")
    assert a != b


def test_scenario_rupture_rupture_disponible() -> None:
    lignes = generer_stock(_pharmacies(), PRODUITS_DEMO, 7, "Amoxicilline")
    dispo = {
        ligne.osm_ref: ligne.disponible for ligne in lignes if ligne.produit_norm == "amoxicilline"
    }
    assert (dispo["n0"], dispo["n1"], dispo["n2"]) == (False, False, True)


def test_scenario_produit_inconnu() -> None:
    with pytest.raises(ValueError):
        generer_stock(_pharmacies(), PRODUITS_DEMO, 1, "produit inexistant")


def test_moins_de_trois_pharmacies() -> None:
    with pytest.raises(ValueError):
        generer_stock(_pharmacies(2), PRODUITS_DEMO, 1, "amoxicilline")


def test_tri_par_distance() -> None:
    tri = trier_par_distance(_pharmacies(), 12.375, -1.60)
    assert [p.osm_ref for p in tri][:3] == ["n5", "n4", "n3"]


def test_agents_couvrent_toutes_les_situations() -> None:
    couvertes = {s for a in generer_agents() for s in a.situations}
    assert set(get_args(Situation)) <= couvertes


def test_agents_fictifs() -> None:
    for agent in generer_agents():
        assert agent.telephone.startswith("NUM-TEST-")
        assert "démo" in agent.nom.casefold()
