"""Charge les lieux de santé OSM (geojsonseq) dans Postgres.

Usage : python -m agent.modules.lieux.chargeur data/osm/ouaga.geojsonseq
"""

import asyncio
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agent.db import get_sessionmaker
from agent.models import OsmPlace, Quarter
from agent.modules.lieux.osm_parse import (
    LieuOsm,
    QuartierOsm,
    extraire_lieux,
    extraire_quartiers,
    lire_features,
    marquer_doublons,
    quartier_proche,
)


@dataclass
class Rapport:
    quartiers: int = 0
    lieux_par_kind: dict[str, int] = field(default_factory=dict)
    doublons: int = 0
    sans_nom: int = 0
    sans_quartier: int = 0


async def _ids_par_ref(
    session: AsyncSession, modele: type[Quarter] | type[OsmPlace]
) -> dict[str, uuid.UUID]:
    resultat = await session.execute(select(modele.osm_ref, modele.id))
    return {ref: id_ for ref, id_ in resultat.all()}


async def _upsert_quartiers(session: AsyncSession, quartiers: list[QuartierOsm]) -> None:
    lignes = [
        {
            "osm_ref": q.osm_ref,
            "name": q.name,
            "name_norm": q.name_norm,
            "place_type": q.place_type,
            "lat": q.lat,
            "lng": q.lng,
        }
        for q in quartiers
    ]
    if not lignes:
        return
    requete = insert(Quarter)
    requete = requete.on_conflict_do_update(
        index_elements=[Quarter.osm_ref],
        set_={c: requete.excluded[c] for c in ("name", "name_norm", "place_type", "lat", "lng")},
    )
    await session.execute(requete, lignes)


async def _upsert_lieux(
    session: AsyncSession,
    lieux: list[LieuOsm],
    quartiers: list[QuartierOsm],
    ids_quartiers: dict[str, uuid.UUID],
) -> int:
    """Insère ou met à jour les lieux ; renvoie le nombre de lieux sans quartier."""
    lignes = []
    sans_quartier = 0
    for lieu in lieux:
        quartier = quartier_proche(lieu.lat, lieu.lng, quartiers)
        if quartier is None:
            sans_quartier += 1
        lignes.append(
            {
                "osm_ref": lieu.osm_ref,
                "kind": lieu.kind,
                "name": lieu.name,
                "osm_tag": lieu.osm_tag,
                "lat": lieu.lat,
                "lng": lieu.lng,
                "quartier_id": ids_quartiers[quartier.osm_ref] if quartier else None,
            }
        )
    if not lignes:
        return 0
    requete = insert(OsmPlace)
    colonnes = ("kind", "name", "osm_tag", "lat", "lng", "quartier_id")
    requete = requete.on_conflict_do_update(
        index_elements=[OsmPlace.osm_ref],
        set_={**{c: requete.excluded[c] for c in colonnes}, "loaded_at": func.now()},
    )
    await session.execute(requete, lignes)
    return sans_quartier


async def _enregistrer_doublons(
    session: AsyncSession, doublons: dict[str, str], ids_lieux: dict[str, uuid.UUID]
) -> None:
    """Remet tous les duplicate_of à NULL puis écrit ceux du chargement courant."""
    await session.execute(update(OsmPlace).values(duplicate_of=None))
    for ref_doublon, ref_garde in doublons.items():
        await session.execute(
            update(OsmPlace)
            .where(OsmPlace.id == ids_lieux[ref_doublon])
            .values(duplicate_of=ids_lieux[ref_garde])
        )


async def _supprimer_quartiers_perimes(session: AsyncSession, quartiers: list[QuartierOsm]) -> None:
    """Retire de la base les quartiers absents du chargement (ex. « Q-Dapoya » devenu « Dapoya »)."""
    if not quartiers:  # garde-fou : un mauvais fichier ne doit pas vider la table
        return
    refs = [q.osm_ref for q in quartiers]
    await session.execute(delete(Quarter).where(Quarter.osm_ref.not_in(refs)))


async def charger(chemin: Path) -> Rapport:
    features = list(lire_features(chemin))
    quartiers = extraire_quartiers(features)
    lieux = extraire_lieux(features)
    doublons = marquer_doublons(lieux)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await _upsert_quartiers(session, quartiers)
        ids_quartiers = await _ids_par_ref(session, Quarter)
        sans_quartier = await _upsert_lieux(session, lieux, quartiers, ids_quartiers)
        await _supprimer_quartiers_perimes(session, quartiers)
        ids_lieux = await _ids_par_ref(session, OsmPlace)
        await _enregistrer_doublons(session, doublons, ids_lieux)
        await session.commit()

    return Rapport(
        quartiers=len(quartiers),
        lieux_par_kind=dict(Counter(lieu.kind for lieu in lieux)),
        doublons=len(doublons),
        sans_nom=sum(1 for lieu in lieux if lieu.name is None),
        sans_quartier=sans_quartier,
    )


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage : python -m agent.modules.lieux.chargeur <fichier.geojsonseq>")
    rapport = asyncio.run(charger(Path(sys.argv[1])))
    print(f"quartiers chargés : {rapport.quartiers}")
    for kind, nombre in sorted(rapport.lieux_par_kind.items()):
        print(f"lieux {kind} : {nombre}")
    print(f"doublons marqués : {rapport.doublons}")
    print(f"lieux sans nom (non proposés) : {rapport.sans_nom}")
    print(f"lieux sans quartier à moins de 3 km : {rapport.sans_quartier}")


if __name__ == "__main__":
    main()
