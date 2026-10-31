"""Données de démo : stock simulé et agents fictifs. Jamais en production."""

from __future__ import annotations

import argparse
import asyncio
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent.db import session_scope  # adapte au chemin réel de ton session_scope
from agent.models import DemoAgent, DemoStock  # adapte le nom de la classe des lieux
from agent.modules.demo.pharmacies import PharmacieDemo, charger_pharmacies, trier_par_distance
from agent.modules.demo.produits import PRODUITS_DEMO, normaliser_produit
from agent.settings import get_setting


@dataclass(frozen=True)
class LigneStock:
    osm_ref: str
    produit_norm: str
    disponible: bool


@dataclass(frozen=True)
class AgentDemo:
    nom: str
    role: str
    situations: tuple[str, ...]
    telephone: str
    horaires: str


AGENTS_DEMO: tuple[AgentDemo, ...] = (
    AgentDemo(
        "Sage-femme démo A.", "sage-femme", ("pregnant",), "NUM-TEST-11", "Tous les jours, 8 h-20 h"
    ),
    AgentDemo(
        "Cardiologue démo B.", "cardiologue", ("heart",), "NUM-TEST-12", "Lundi-vendredi, 8 h-16 h"
    ),
    AgentDemo(
        "Généraliste démo C.",
        "généraliste",
        ("asthma", "other"),
        "NUM-TEST-13",
        "Tous les jours, 7 h-22 h",
    ),
    AgentDemo(
        "Pédiatre démo D.", "pédiatre", ("sick_baby",), "NUM-TEST-14", "Tous les jours, 8 h-20 h"
    ),
    AgentDemo("Urgentiste démo E.", "urgentiste", ("accident",), "NUM-TEST-15", "24 h/24"),
)


def generer_stock(
    pharmacies: Sequence[PharmacieDemo],
    produits: Sequence[str],
    graine: int,
    produit_scenario: str,
    proba_dispo: float = 0.5,
) -> list[LigneStock]:
    """Stock simulé, reproductible. `pharmacies` doit arriver triée par distance.

    Scénario : pour `produit_scenario`, les 2 premières pharmacies sont en rupture
    et la 3e l'a.
    """
    if len(pharmacies) < 3:
        raise ValueError("Il faut au moins 3 pharmacies pour le scénario.")
    normes = list(dict.fromkeys(normaliser_produit(p) for p in produits))
    scenario = normaliser_produit(produit_scenario)
    if scenario not in normes:
        raise ValueError("Le produit du scénario doit figurer dans la liste des produits.")

    rng = random.Random(graine)  # noqa: S311  (simulation reproductible, pas de cryptographie)
    lignes: list[LigneStock] = []
    for rang, pharmacie in enumerate(pharmacies):
        for produit in normes:
            tirage = rng.random() < proba_dispo  # toujours tiré : séquence stable
            if produit == scenario and rang < 3:
                disponible = rang == 2
            else:
                disponible = tirage
            lignes.append(LigneStock(pharmacie.osm_ref, produit, disponible))
    return lignes


def generer_agents() -> tuple[AgentDemo, ...]:
    return AGENTS_DEMO


async def ecrire_stock(session: AsyncSession, lignes: Sequence[LigneStock]) -> None:
    valeurs = [
        {
            "id": uuid.uuid4(),
            "osm_ref": ligne.osm_ref,
            "produit_norm": ligne.produit_norm,
            "disponible": ligne.disponible,
        }
        for ligne in lignes
    ]
    requete = insert(DemoStock).values(valeurs)
    requete = requete.on_conflict_do_update(
        index_elements=["osm_ref", "produit_norm"],
        set_={"disponible": requete.excluded.disponible, "mis_a_jour_le": func.now()},
    )
    await session.execute(requete)


async def ecrire_agents(session: AsyncSession, agents: Sequence[AgentDemo]) -> None:
    await session.execute(delete(DemoAgent))
    session.add_all(
        DemoAgent(
            nom=a.nom,
            role=a.role,
            situations=list(a.situations),
            telephone=a.telephone,
            horaires=a.horaires,
        )
        for a in agents
    )


async def remplir(lat: float, lng: float, graine: int, produit_scenario: str) -> None:
    async with session_scope() as session:
        pharmacies = trier_par_distance(await charger_pharmacies(session), lat, lng)
        lignes = generer_stock(pharmacies, PRODUITS_DEMO, graine, produit_scenario)
        await ecrire_stock(session, lignes)
        await ecrire_agents(session, generer_agents())
        await session.commit()
    print(
        f"{len(pharmacies)} pharmacies, {len(lignes)} lignes de stock, {len(AGENTS_DEMO)} agents."
    )
    print(f"Scénario « {produit_scenario} » : rupture, rupture, disponible :")
    for rang, p in enumerate(pharmacies[:3]):
        print(f"  {rang + 1}. {p.nom} ({'disponible' if rang == 2 else 'rupture'})")


def main() -> None:
    if not get_setting().DEMO_MODE:
        raise SystemExit("DEMO_MODE est faux : seed_demo refusé.")
    parseur = argparse.ArgumentParser(description="Remplit les tables de démo.")
    parseur.add_argument("--lat", type=float, required=True)
    parseur.add_argument("--lng", type=float, required=True)
    parseur.add_argument("--graine", type=int, default=42)
    parseur.add_argument("--produit", default="amoxicilline")
    args = parseur.parse_args()
    asyncio.run(remplir(args.lat, args.lng, args.graine, args.produit))


if __name__ == "__main__":
    main()
