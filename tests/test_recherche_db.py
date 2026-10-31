"""Tests de chercher_lieux sur SQLite en mémoire (modèle SQLAlchemy sans PostgreSQL).

Nécessite aiosqlite (`uv add --dev aiosqlite`) ; sinon le fichier est ignoré.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from agent.models import (  # noqa: E402
    Base,
    ConfirmedPlace,
    OnCallPharmacy,
    OsmPlace,
    Quarter,
)
from agent.modules.lieux.recherche import Garde, Statut, chercher_lieux  # noqa: E402

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
TABLES = [
    Quarter.__table__,
    OsmPlace.__table__,
    ConfirmedPlace.__table__,
    OnCallPharmacy.__table__,
]


def _lieu(
    ref: str,
    nom: str | None,
    kind: str,
    lat: float,
    lng: float,
    quartier_id: uuid.UUID | None = None,
    duplicate_of: uuid.UUID | None = None,
) -> OsmPlace:
    return OsmPlace(
        osm_ref=ref,
        kind=kind,
        name=nom,
        osm_tag="amenity=x",
        lat=lat,
        lng=lng,
        quartier_id=quartier_id,
        duplicate_of=duplicate_of,
    )


def _executer(scenario: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
    async def _run() -> Any:
        moteur = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with moteur.begin() as connexion:
            await connexion.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))
        async with async_sessionmaker(moteur, expire_on_commit=False)() as session:
            resultat = await scenario(session)
        await moteur.dispose()
        return resultat

    return asyncio.run(_run())


async def _donnees(session: AsyncSession) -> dict[str, uuid.UUID]:
    dapoya = Quarter(
        osm_ref="n1", name="Dapoya", name_norm="dapoya", place_type="suburb", lat=12.37, lng=-1.52
    )
    session.add(dapoya)
    await session.flush()
    original = _lieu("a1", "CSPS", "health_center", 12.371, -1.52, dapoya.id)
    session.add(original)
    await session.flush()
    session.add_all(
        [
            original,
            _lieu("n2", "Clinique Saint Luc", "health_center", 12.375, -1.52),
            _lieu("n3", "Maternité", "health_center", 12.380, -1.52),
            _lieu("n4", "Hôpital Lointain", "health_center", 12.450, -1.52),
            _lieu("n5", None, "health_center", 12.3701, -1.52),  # sans nom
            _lieu("n6", "  ", "health_center", 12.3702, -1.52),  # nom blanc
            _lieu("n7", "CSPS", "health_center", 12.3703, -1.52, duplicate_of=original.id),
            _lieu("n10", "Pharmacie Camille", "pharmacy", 12.372, -1.52),
            _lieu("n11", "Pharmacie du Marché", "pharmacy", 12.376, -1.52),
            _lieu("n12", "Pharmacie de la Paix", "pharmacy", 12.385, -1.52),
            _lieu("n13", "Pharmacie Sud", "pharmacy", 12.400, -1.52),
            ConfirmedPlace(osm_ref="a1", phone="+226 00 00 00 00", hours_text="7h-17h"),
        ]
    )
    await session.commit()
    return {"dapoya": dapoya.id}


def test_centre_par_position_trie_et_ignore_sans_nom_et_doublon() -> None:
    async def scenario(session: AsyncSession) -> Any:
        await _donnees(session)
        return await chercher_lieux(
            session, {"kind": "centre de santé", "lat": 12.37, "lng": -1.52}, maintenant=NOW
        )

    r = _executer(scenario)
    assert r.statut == Statut.OK
    assert r.origine == "position"
    assert [lieu.osm_ref for lieu in r.lieux] == ["a1", "n2", "n3"]
    premier = r.lieux[0]
    assert premier.label == "CSPS (Dapoya)"
    assert (premier.phone, premier.hours_text) == ("+226 00 00 00 00", "7h-17h")
    assert r.lieux[1].hours_text is None
    assert r.garde == Garde.NON_DEMANDEE


def test_depart_par_quartier_avec_prefixe_et_accents() -> None:
    async def scenario(session: AsyncSession) -> Any:
        await _donnees(session)
        return await chercher_lieux(
            session, {"kind": "pharmacie", "quartier": "Q-DAPOYA "}, maintenant=NOW
        )

    r = _executer(scenario)
    assert r.statut == Statut.OK
    assert (r.origine, r.quartier_depart) == ("quartier", "Dapoya")
    assert [lieu.osm_ref for lieu in r.lieux] == ["n10", "n11", "n12"]


def test_la_position_l_emporte_sur_le_quartier() -> None:
    async def scenario(session: AsyncSession) -> Any:
        await _donnees(session)
        params = {"kind": "pharmacie", "quartier": "Zogona", "lat": 12.40, "lng": -1.52}
        return await chercher_lieux(session, params, maintenant=NOW)

    r = _executer(scenario)
    assert r.statut == Statut.OK
    assert r.origine == "position"
    assert r.lieux[0].osm_ref == "n13"


@pytest.mark.parametrize(
    ("params", "statut"),
    [
        ({}, Statut.TYPE_MANQUANT),
        ({"kind": ""}, Statut.TYPE_MANQUANT),
        ({"kind": "pharmacie"}, Statut.POSITION_MANQUANTE),
        ({"kind": "pharmacie", "quartier": "  "}, Statut.POSITION_MANQUANTE),
        ({"kind": "pharmacie", "lat": 12.37}, Statut.POSITION_MANQUANTE),
        ({"kind": "pharmacie", "quartier": "Zogona"}, Statut.QUARTIER_INCONNU),
    ],
)
def test_statuts_sans_resultat(params: dict[str, object], statut: Statut) -> None:
    async def scenario(session: AsyncSession) -> Any:
        await _donnees(session)
        return await chercher_lieux(session, params, maintenant=NOW)

    r = _executer(scenario)
    assert r.statut == statut
    assert r.lieux == []


def test_aucun_lieu_dans_une_base_vide() -> None:
    async def scenario(session: AsyncSession) -> Any:
        return await chercher_lieux(
            session, {"kind": "pharmacie", "lat": 12.37, "lng": -1.52}, maintenant=NOW
        )

    assert _executer(scenario).statut == Statut.AUCUN_LIEU


def test_garde_non_confirmee_si_aucune_garde_en_cours() -> None:
    async def scenario(session: AsyncSession) -> Any:
        await _donnees(session)
        session.add(  # garde passée : ne compte pas
            OnCallPharmacy(
                osm_ref="n13",
                start_at=NOW - timedelta(days=8),
                end_at=NOW - timedelta(days=1),
                source="test",
            )
        )
        await session.commit()
        params = {"kind": "pharmacie de garde", "lat": 12.37, "lng": -1.52}
        return await chercher_lieux(session, params, maintenant=NOW)

    r = _executer(scenario)
    assert r.garde == Garde.NON_CONFIRMEE
    assert [lieu.osm_ref for lieu in r.lieux] == ["n10", "n11", "n12"]


def test_garde_confirmee_ne_liste_que_les_pharmacies_de_garde() -> None:
    async def scenario(session: AsyncSession) -> Any:
        await _donnees(session)
        session.add(
            OnCallPharmacy(
                osm_ref="n13",
                start_at=NOW - timedelta(hours=2),
                end_at=NOW + timedelta(hours=10),
                source="test",
            )
        )
        await session.commit()
        params = {"kind": "garde", "lat": 12.37, "lng": -1.52}
        return await chercher_lieux(session, params, maintenant=NOW)

    r = _executer(scenario)
    assert r.garde == Garde.CONFIRMEE
    assert [lieu.osm_ref for lieu in r.lieux] == ["n13"]


def test_garde_hors_proposables_retombe_sur_non_confirmee() -> None:
    async def scenario(session: AsyncSession) -> Any:
        await _donnees(session)
        session.add(  # n99 n'existe pas parmi les lieux proposables
            OnCallPharmacy(
                osm_ref="n99",
                start_at=NOW - timedelta(hours=1),
                end_at=NOW + timedelta(hours=1),
                source="test",
            )
        )
        await session.commit()
        params = {"kind": "garde", "lat": 12.37, "lng": -1.52}
        return await chercher_lieux(session, params, maintenant=NOW)

    r = _executer(scenario)
    assert r.garde == Garde.NON_CONFIRMEE
    assert len(r.lieux) == 3


def test_open_now_est_signale_comme_ignore() -> None:
    async def scenario(session: AsyncSession) -> Any:
        await _donnees(session)
        params = {"kind": "pharmacie", "lat": 12.37, "lng": -1.52, "open_now": True}
        return await chercher_lieux(session, params, maintenant=NOW)

    r = _executer(scenario)
    assert r.open_now_ignore is True
    assert r.statut == Statut.OK