"""Mise en forme WhatsApp des résultats de stock (démo)."""

from __future__ import annotations

from agent.modules.stock.recherche import PharmacieDispo, RechercheStock, StatutStock


def _distance(km: float) -> str:
    if km < 1:
        return f"{round(km * 1000)} m"
    return f"{km:.1f}".replace(".", ",") + " km"


def _pharmacies(n: int) -> str:
    return f"{n} pharmacie" + ("s" if n > 1 else "")


def _ligne(p: PharmacieDispo) -> str:
    return f"* {p.nom} : {_distance(p.distance_km)}"


def rendre_stock(recherche: RechercheStock, sobre: bool) -> str:
    if recherche.statut is StatutStock.PRODUIT_INCONNU:
        return (
            "Je ne reconnais pas ce médicament dans la démo. Pouvez-vous me donner un autre nom ?"
        )
    if recherche.statut is StatutStock.POSITION_MANQUANTE:
        return "J'ai besoin de votre position pour chercher. Pouvez-vous la partager ?"
    if recherche.statut is StatutStock.AUCUNE:
        return (
            f"J'ai vérifié {_pharmacies(recherche.ruptures_avant)} près de vous : "
            "aucune n'a ce produit pour le moment (démo). "
            "Pouvez-vous me donner un autre nom de médicament ?"
        )
    emoji = "" if sobre else " 💊"
    intro = f"Voici où trouver {recherche.produit}"
    if recherche.ruptures_avant > 0:
        intro = f"J'ai vérifié {_pharmacies(recherche.ruptures_avant)} avant : en rupture. {intro}"
    lignes = "\n\n".join(_ligne(p) for p in recherche.disponibles)
    return f"{intro} (démo){emoji} :\n\n{lignes}\n\nDisponibilité simulée. Appelez avant de vous déplacer."
