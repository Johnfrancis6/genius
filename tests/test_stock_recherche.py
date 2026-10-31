import pytest

from agent.modules.demo.pharmacies import PharmacieDemo
from agent.modules.stock.recherche import parcourir, reconnaitre_produit


def _pharmacies(n: int = 6) -> list[PharmacieDemo]:
    return [PharmacieDemo(f"n{i}", f"Pharmacie {i}", 12.37, -1.60) for i in range(n)]


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("J'ai besoin d'amoxicilline 500 mg", "amoxicilline"),
        ("PARACÉTAMOL", "paracetamol"),
        ("Vitamine C", "vitamine c"),
        ("du doliprane", None),
        ("", None),
    ],
)
def test_reconnaitre_produit(texte: str, attendu: str | None) -> None:
    assert reconnaitre_produit(texte) == attendu


def test_parcourir_compte_les_ruptures_avant() -> None:
    avant, trouvees = parcourir(_pharmacies(), {"n2": True, "n4": True})
    assert avant == 2
    assert [p.osm_ref for p in trouvees] == ["n2", "n4"]


def test_parcourir_limite_les_disponibles() -> None:
    dispo = {f"n{i}": True for i in range(6)}
    _, trouvees = parcourir(_pharmacies(), dispo, max_dispo=3)
    assert len(trouvees) == 3


def test_parcourir_aucune_disponible() -> None:
    avant, trouvees = parcourir(_pharmacies(), {"n1": False})
    assert (avant, trouvees) == (6, [])
