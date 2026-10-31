from agent.conversation.meny import MENU
from agent.conversation.nodes import _manquants
from agent.modules.stock.recherche import PharmacieDispo, RechercheStock, StatutStock
from agent.modules.stock.rendu import rendre_stock


def test_titres_menu_courts() -> None:
    assert all(len(ligne.titre) <= 24 for ligne in MENU)
    assert len({ligne.callback for ligne in MENU}) == len(MENU)


def test_manquants_stock() -> None:
    assert _manquants({"search": {}, "mobility": None, "situation": None}, False, "stock") == [
        "product",
        "location",
    ]
    complet = {
        "search": {"produit": "zinc", "lat": 1.0, "lng": 2.0},
        "mobility": None,
        "situation": None,
    }
    assert _manquants(complet, False, "stock") == []


def test_rendu_stock_ok() -> None:
    dispo = (PharmacieDispo("n2", "Pharmacie Test", 0.69),)
    texte = rendre_stock(RechercheStock(StatutStock.OK, "amoxicilline", 2, dispo), False)
    assert "2 pharmacies" in texte
    assert "(démo)" in texte
    assert "690 m" in texte


def test_rendu_stock_sans_rupture_avant() -> None:
    dispo = (PharmacieDispo("n0", "Pharmacie Test", 2.1),)
    texte = rendre_stock(RechercheStock(StatutStock.OK, "zinc", 0, dispo), True)
    assert "vérifié" not in texte
    assert "2,1 km" in texte
    assert "💊" not in texte
