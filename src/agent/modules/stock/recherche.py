"""Recherche de stock (démo) : première pharmacie proche qui a le produit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.conversation.state import SearchParams
from agent.models import DemoStock
from agent.modules.demo.pharmacies import (
    PharmacieDemo,
    charger_pharmacies,
    distance_km,
    trier_par_distance,
)
from agent.modules.demo.produits import PRODUITS_DEMO, normaliser_produit

MAX_VERIFIEES = 8
MAX_DISPONIBLES = 3


class StatutStock(StrEnum):
    OK = "ok"
    PRODUIT_INCONNU = "produit_inconnu"
    POSITION_MANQUANTE = "position_manquante"
    AUCUNE = "aucune"


@dataclass(frozen=True)
class PharmacieDispo:
    osm_ref: str
    nom: str
    distance_km: float


@dataclass(frozen=True)
class RechercheStock:
    statut: StatutStock
    produit: str | None = None
    ruptures_avant: int = 0
    disponibles: tuple[PharmacieDispo, ...] = ()


def reconnaitre_produit(texte: str) -> str | None:
    """Produit de démo dont tous les mots figurent dans le texte, sinon None."""
    mots = set(normaliser_produit(texte).split())
    for produit in PRODUITS_DEMO:
        norme = normaliser_produit(produit)
        if set(norme.split()) <= mots:
            return norme
    return None


def parcourir(
    pharmacies: Sequence[PharmacieDemo],
    dispo: Mapping[str, bool],
    max_dispo: int = MAX_DISPONIBLES,
) -> tuple[int, list[PharmacieDemo]]:
    """`pharmacies` triées par distance, déjà limitées à la fenêtre vérifiée.

    Retourne (ruptures avant la première disponible, pharmacies disponibles).
    Une pharmacie sans ligne de stock compte comme en rupture.
    """
    trouvees = [p for p in pharmacies if dispo.get(p.osm_ref)][:max_dispo]
    if not trouvees:
        return len(pharmacies), []
    return list(pharmacies).index(trouvees[0]), trouvees


async def chercher_stock(session: AsyncSession, search: SearchParams) -> RechercheStock:
    produit = reconnaitre_produit(search.get("produit", ""))
    if produit is None:
        return RechercheStock(StatutStock.PRODUIT_INCONNU)
    lat, lng = search.get("lat"), search.get("lng")
    if lat is None or lng is None:
        return RechercheStock(StatutStock.POSITION_MANQUANTE, produit)

    tous = await charger_pharmacies(session)
    fenetre = trier_par_distance(tous, lat, lng)[:MAX_VERIFIEES]
    resultat = await session.execute(
        select(DemoStock.osm_ref, DemoStock.disponible).where(
            DemoStock.produit_norm == produit,
            DemoStock.osm_ref.in_([p.osm_ref for p in fenetre]),
        )
    )
    ruptures, trouvees = parcourir(fenetre, {r.osm_ref: r.disponible for r in resultat})
    if not trouvees:
        return RechercheStock(StatutStock.AUCUNE, produit, ruptures)
    return RechercheStock(
        StatutStock.OK,
        produit,
        ruptures,
        tuple(
            PharmacieDispo(p.osm_ref, p.nom, distance_km(lat, lng, p.lat, p.lng)) for p in trouvees
        ),
    )
