"""Recherche des lieux de santé les plus proches (pharmacies, centres de santé).

Aucune mise en forme WhatsApp ici : le module renvoie des données et un statut,
le graphe choisit la réponse.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.models import ConfirmedPlace, OnCallPharmacy, OsmPlace, Quarter
from agent.modules.lieux.osm_parse import distance_m, normaliser_nom, retirer_prefixe_q

NB_RESULTATS = 3

# Noms qui ne permettent pas, seuls, de reconnaître un lieu : on ajoute le quartier.
GENERIQUES = frozenset(
    {
        "csps",
        "cm",
        "dispensaire",
        "maternite",
        "clinique",
        "pharmacie",
        "cabinet medical",
        "centre medical",
        "hopital",
        "infirmerie",
    }
)


class Statut(StrEnum):
    OK = "ok"
    TYPE_MANQUANT = "type_manquant"
    POSITION_MANQUANTE = "position_manquante"
    QUARTIER_INCONNU = "quartier_inconnu"
    AUCUN_LIEU = "aucun_lieu"


class Garde(StrEnum):
    NON_DEMANDEE = "non_demandee"
    CONFIRMEE = "confirmee"  # liste issue de on_call_pharmacies
    NON_CONFIRMEE = "non_confirmee"  # pharmacies proches, garde non vérifiée


@dataclass(frozen=True)
class Lieu:
    osm_ref: str
    kind: str
    name: str
    label: str
    quartier: str | None
    distance_m: float
    phone: str | None
    hours_text: str | None  # None = « horaires non confirmés, appelez avant »


@dataclass(frozen=True)
class Recherche:
    statut: Statut
    lieux: list[Lieu]
    garde: Garde = Garde.NON_DEMANDEE
    origine: str | None = None  # "position" ou "quartier"
    quartier_depart: str | None = None
    open_now_ignore: bool = False  # OSM n'a pas d'horaires fiables


@dataclass(frozen=True)
class _Candidat:
    osm_ref: str
    kind: str
    name: str
    lat: float
    lng: float
    quartier: str | None
    phone: str | None
    hours_text: str | None


def type_de_recherche(kind: object) -> tuple[str | None, bool]:
    """('pharmacy' | 'health_center' | None, garde_demandee) d'après le texte libre `kind`."""
    if not isinstance(kind, str) or not normaliser_nom(kind):
        return None, False
    texte = normaliser_nom(kind)
    if "garde" in texte:
        return "pharmacy", True
    if "pharm" in texte:
        return "pharmacy", False
    return "health_center", False


def construire_libelle(name: str, quartier: str | None) -> str:
    """Nom OSM ; suivi du quartier entre parenthèses si le nom est générique."""
    if quartier and normaliser_nom(name) in GENERIQUES:
        return f"{name} ({quartier})"
    return name


def _nombre(valeur: object) -> float | None:
    if isinstance(valeur, bool) or not isinstance(valeur, int | float):
        return None
    return float(valeur)


def classer(
    candidats: list[_Candidat], lat: float, lng: float, n: int = NB_RESULTATS
) -> list[Lieu]:
    """Les n candidats les plus proches (égalités départagées par osm_ref)."""
    avec_distance = sorted(
        ((distance_m(lat, lng, c.lat, c.lng), c) for c in candidats),
        key=lambda t: (t[0], t[1].osm_ref),
    )
    return [
        Lieu(
            osm_ref=c.osm_ref,
            kind=c.kind,
            name=c.name,
            label=construire_libelle(c.name, c.quartier),
            quartier=c.quartier,
            distance_m=d,
            phone=c.phone,
            hours_text=c.hours_text,
        )
        for d, c in avec_distance[:n]
    ]


async def _trouver_quartier(session: AsyncSession, texte: str) -> Quarter | None:
    nom_norm = normaliser_nom(retirer_prefixe_q(texte))
    if not nom_norm:
        return None
    requete = (
        select(Quarter).where(Quarter.name_norm == nom_norm).order_by(Quarter.osm_ref).limit(1)
    )
    return (await session.execute(requete)).scalar_one_or_none()


async def _candidats(session: AsyncSession, kind: str) -> list[_Candidat]:
    requete = (
        select(
            OsmPlace.osm_ref,
            OsmPlace.name,
            OsmPlace.lat,
            OsmPlace.lng,
            Quarter.name,
            ConfirmedPlace.phone,
            ConfirmedPlace.hours_text,
        )
        .outerjoin(Quarter, Quarter.id == OsmPlace.quartier_id)
        .outerjoin(ConfirmedPlace, ConfirmedPlace.osm_ref == OsmPlace.osm_ref)
        .where(
            OsmPlace.kind == kind,
            OsmPlace.name.is_not(None),
            OsmPlace.duplicate_of.is_(None),
        )
    )
    candidats = []
    for osm_ref, name, lat, lng, quartier, phone, hours_text in await session.execute(requete):
        if not name or not name.strip():
            continue
        candidats.append(
            _Candidat(osm_ref, kind, name.strip(), lat, lng, quartier, phone, hours_text)
        )
    return candidats


async def _refs_de_garde(session: AsyncSession, maintenant: datetime) -> set[str]:
    requete = select(OnCallPharmacy.osm_ref).where(
        OnCallPharmacy.start_at <= maintenant, OnCallPharmacy.end_at > maintenant
    )
    return set((await session.execute(requete)).scalars())


async def chercher_lieux(
    session: AsyncSession,
    params: Mapping[str, object],
    *,
    maintenant: datetime | None = None,
) -> Recherche:
    """Cherche les 3 lieux les plus proches d'après SearchParams (kind, quartier, lat, lng)."""
    maintenant = maintenant or datetime.now(UTC)
    open_now = bool(params.get("open_now"))

    kind, garde_demandee = type_de_recherche(params.get("kind"))
    if kind is None:
        return Recherche(Statut.TYPE_MANQUANT, [], open_now_ignore=open_now)

    lat, lng = _nombre(params.get("lat")), _nombre(params.get("lng"))
    origine: str
    quartier_depart: str | None = None
    if lat is not None and lng is not None:
        origine = "position"
    else:
        texte = params.get("quartier")
        if not isinstance(texte, str) or not texte.strip():
            return Recherche(Statut.POSITION_MANQUANTE, [], open_now_ignore=open_now)
        quartier = await _trouver_quartier(session, texte)
        if quartier is None:
            return Recherche(Statut.QUARTIER_INCONNU, [], open_now_ignore=open_now)
        lat, lng, origine, quartier_depart = quartier.lat, quartier.lng, "quartier", quartier.name

    candidats = await _candidats(session, kind)
    garde = Garde.NON_DEMANDEE
    if garde_demandee:
        refs = await _refs_de_garde(session, maintenant)
        de_garde = [c for c in candidats if c.osm_ref in refs]
        if de_garde:
            candidats, garde = de_garde, Garde.CONFIRMEE
        else:
            garde = Garde.NON_CONFIRMEE

    lieux = classer(candidats, lat, lng)
    return Recherche(
        statut=Statut.OK if lieux else Statut.AUCUN_LIEU,
        lieux=lieux,
        garde=garde,
        origine=origine,
        quartier_depart=quartier_depart,
        open_now_ignore=open_now,
    )
