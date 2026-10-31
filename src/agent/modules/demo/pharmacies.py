"""Pharmacies proposables (OSM) : chargement et tri par distance, partagés par la démo."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.models import OsmPlace  # adapte le nom de la classe des lieux
from agent.modules.demo.produits import normaliser_produit

EXCLUS_NOM = re.compile(
    r"\b(centre medical|centre de sante|polyclinique|clinique|csps|dispensaire|hopital|cabinet)\b"
)


@dataclass(frozen=True)
class PharmacieDemo:
    osm_ref: str
    nom: str
    lat: float
    lng: float


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def trier_par_distance(
    pharmacies: Sequence[PharmacieDemo], lat: float, lng: float
) -> list[PharmacieDemo]:
    return sorted(pharmacies, key=lambda p: distance_km(lat, lng, p.lat, p.lng))


async def charger_pharmacies(session: AsyncSession) -> list[PharmacieDemo]:
    resultat = await session.execute(
        select(OsmPlace.osm_ref, OsmPlace.name, OsmPlace.lat, OsmPlace.lng).where(
            OsmPlace.kind == "pharmacy",
            OsmPlace.name.is_not(None),
            OsmPlace.name != "",
            OsmPlace.duplicate_of.is_(None),
        )
    )
    return [
        PharmacieDemo(r.osm_ref, r.name, r.lat, r.lng)
        for r in resultat
        if not EXCLUS_NOM.search(normaliser_produit(r.name))
    ]
