"""Lecture et nettoyage des lieux de santé OpenStreetMap (aucun accès base)."""

import json
import math
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLACE_TYPES = frozenset({"quarter", "neighbourhood", "suburb", "village", "hamlet", "town"})
AMENITIES_CENTRE = frozenset({"hospital", "clinic", "doctors"})
HEALTHCARE_CENTRE = frozenset({"centre", "doctor", "clinic", "hospital", "birthing_centre"})
FORMES = frozenset({"Point", "Polygon", "MultiPolygon"})

SEUIL_DOUBLON_M = 150.0
SEUIL_QUARTIER_M = 3000.0
RAYON_TERRE_M = 6_371_008.8

_APOSTROPHES = str.maketrans({"´": "'", "’": "'", "‘": "'", "`": "'"})


@dataclass(frozen=True)
class LieuOsm:
    osm_ref: str
    kind: str
    name: str | None
    osm_tag: str
    lat: float
    lng: float
    is_polygon: bool


@dataclass(frozen=True)
class QuartierOsm:
    osm_ref: str
    name: str
    name_norm: str
    place_type: str
    lat: float
    lng: float


def lire_features(chemin: Path) -> Iterator[dict[str, Any]]:
    """Lit un fichier geojsonseq (une Feature par ligne, séparateur RS éventuel en tête)."""
    with open(chemin, encoding="utf-8") as fichier:
        for ligne in fichier:
            ligne = ligne.strip().lstrip("\x1e")
            if ligne:
                yield json.loads(ligne)


def centre(geometry: dict[str, Any]) -> tuple[float, float]:
    """Renvoie (lat, lng). GeoJSON stocke (lng, lat) : l'ordre est inversé ici."""
    type_geometrie = geometry["type"]
    coordonnees = geometry["coordinates"]
    if type_geometrie == "Point":
        return coordonnees[1], coordonnees[0]
    if type_geometrie == "MultiPolygon":
        anneau = coordonnees[0][0]
    elif type_geometrie == "Polygon":
        anneau = coordonnees[0]
    else:
        raise ValueError(f"géométrie non gérée : {type_geometrie}")
    if len(anneau) > 1 and anneau[0] == anneau[-1]:
        anneau = anneau[:-1]
    lng = sum(point[0] for point in anneau) / len(anneau)
    lat = sum(point[1] for point in anneau) / len(anneau)
    return lat, lng


def normaliser_nom(texte: str) -> str:
    """Minuscules, sans accents, apostrophes unifiées, espaces réduits."""
    texte = texte.translate(_APOSTROPHES)
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texte.lower()).strip()


def classer(props: dict[str, Any]) -> str | None:
    """'pharmacy', 'health_center' ou None (lieu ignoré)."""
    amenity = props.get("amenity")
    healthcare = props.get("healthcare")
    if amenity == "pharmacy" or healthcare == "pharmacy":
        return "pharmacy"
    if amenity in AMENITIES_CENTRE or healthcare in HEALTHCARE_CENTRE:
        return "health_center"
    return None


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance haversine en mètres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * RAYON_TERRE_M * math.asin(math.sqrt(a))


_PREFIXE_Q = re.compile(r"^q(?:\s*-\s*|\s+)(?=\S)", re.IGNORECASE)


def retirer_prefixe_q(nom: str) -> str:
    """'Q-Dapoya' -> 'Dapoya', 'Q Tebedogo' -> 'Tebedogo'. Début de nom seulement, casse ignorée."""
    return _PREFIXE_Q.sub("", nom.strip(), count=1).strip()


def fusionner_quartiers_osm(quartiers: Iterable[QuartierOsm]) -> list[QuartierOsm]:
    """Un seul quartier par name_norm : celui dont l'osm_ref est le plus petit (ordre des chaînes)."""
    gardes: dict[str, QuartierOsm] = {}
    for quartier in sorted(quartiers, key=lambda q: q.osm_ref):
        gardes.setdefault(quartier.name_norm, quartier)
    return list(gardes.values())


def extraire_quartiers(features: Iterable[dict[str, Any]]) -> list[QuartierOsm]:
    resultat: dict[str, QuartierOsm] = {}
    for feature in features:
        props = feature.get("properties") or {}
        type_place = props.get("place")
        nom = retirer_prefixe_q((props.get("name") or "").strip())
        osm_ref = feature.get("id")
        geometrie = feature.get("geometry") or {}
        if type_place not in PLACE_TYPES or not nom or not osm_ref:
            continue
        if geometrie.get("type") not in FORMES:
            continue
        lat, lng = centre(geometrie)
        resultat[osm_ref] = QuartierOsm(
            osm_ref=osm_ref,
            name=nom,
            name_norm=normaliser_nom(nom),
            place_type=type_place,
            lat=lat,
            lng=lng,
        )
    return fusionner_quartiers_osm(resultat.values())


def extraire_lieux(features: Iterable[dict[str, Any]]) -> list[LieuOsm]:
    resultat: dict[str, LieuOsm] = {}
    for feature in features:
        props = feature.get("properties") or {}
        osm_ref = feature.get("id")
        geometrie = feature.get("geometry") or {}
        kind = classer(props)
        if kind is None or not osm_ref or geometrie.get("type") not in FORMES:
            continue
        lat, lng = centre(geometrie)
        resultat[osm_ref] = LieuOsm(
            osm_ref=osm_ref,
            kind=kind,
            name=(props.get("name") or "").strip() or None,
            osm_tag=props.get("amenity") or props.get("healthcare") or "",
            lat=lat,
            lng=lng,
            is_polygon=geometrie["type"] != "Point",
        )
    return list(resultat.values())


def quartier_proche(
    lat: float,
    lng: float,
    quartiers: Iterable[QuartierOsm],
    max_m: float = SEUIL_QUARTIER_M,
) -> QuartierOsm | None:
    """Quartier le plus proche, ou None s'il est à plus de max_m mètres."""
    meilleur: QuartierOsm | None = None
    meilleure_distance = max_m
    for quartier in quartiers:
        d = distance_m(lat, lng, quartier.lat, quartier.lng)
        if d <= meilleure_distance:
            meilleur, meilleure_distance = quartier, d
    return meilleur


def marquer_doublons(lieux: Iterable[LieuOsm]) -> dict[str, str]:
    """osm_ref du doublon -> osm_ref du lieu gardé.

    Glouton déterministe : polygones d'abord, puis osm_ref croissant (ordre texte).
    Un lieu est un doublon s'il existe déjà un lieu gardé de même kind, de même nom
    normalisé non vide, à moins de SEUIL_DOUBLON_M mètres. Les lieux sans nom ne
    sont jamais fusionnés.
    """
    gardes: list[tuple[LieuOsm, str]] = []
    doublons: dict[str, str] = {}
    for lieu in sorted(lieux, key=lambda x: (not x.is_polygon, x.osm_ref)):
        nom = normaliser_nom(lieu.name) if lieu.name else ""
        garde = None
        if nom:
            for candidat, nom_candidat in gardes:
                if (
                    candidat.kind == lieu.kind
                    and nom_candidat == nom
                    and distance_m(lieu.lat, lieu.lng, candidat.lat, candidat.lng) < SEUIL_DOUBLON_M
                ):
                    garde = candidat
                    break
        if garde is None:
            gardes.append((lieu, nom))
        else:
            doublons[lieu.osm_ref] = garde.osm_ref
    return doublons
