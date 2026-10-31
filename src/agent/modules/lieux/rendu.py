"""Mise en forme WhatsApp d'une Recherche de lieux (aucun accès base, aucun LLM)."""

from __future__ import annotations

from typing import assert_never

from agent.modules.lieux.recherche import Garde, Lieu, Recherche, Statut

_PLURIEL_PAR_KIND = {"pharmacy": "pharmacies", "health_center": "centres de santé"}


def formater_distance(metres: float) -> str:
    """Moins de 1000 m : '350 m' (arrondi à 10 m) ; sinon '1,2 km'."""
    arrondi = round(metres / 10) * 10
    if arrondi < 1000:
        return f"{arrondi} m"
    return f"{metres / 1000:.1f}".replace(".", ",") + " km"


def rendre_lieu(lieu: Lieu) -> str:
    lignes = [f"• {lieu.label} : {formater_distance(lieu.distance_m)}"]
    if lieu.phone:
        lignes.append(f"  Tél. : {lieu.phone}")
    if lieu.hours_text:
        lignes.append(f"  Horaires : {lieu.hours_text}")
    elif lieu.phone:
        lignes.append("  Horaires non confirmés, appelez avant.")
    else:
        lignes.append("  Horaires non confirmés.")
    return "\n".join(lignes)


def _question(texte: str, sobre: bool, emoji: str) -> str:
    return texte if sobre else f"{texte} {emoji}"


def _rendre_ok(recherche: Recherche) -> str:
    if recherche.garde is Garde.CONFIRMEE:
        nom = "pharmacies de garde"
    else:
        nom = _PLURIEL_PAR_KIND.get(recherche.lieux[0].kind, "lieux")
    if recherche.origine == "quartier" and recherche.quartier_depart:
        depart = f"près de {recherche.quartier_depart}"
    else:
        depart = "près de vous"
    entete = [f"Voici les {nom} les plus proches, {depart} :"]
    if recherche.garde is Garde.NON_CONFIRMEE:
        entete.append(
            "Je n'ai pas pu confirmer quelles pharmacies sont de garde : "
            "appelez avant de vous déplacer."
        )
    if recherche.open_now_ignore:
        entete.append("Je ne peux pas vérifier si elles sont ouvertes en ce moment.")
    blocs = [rendre_lieu(lieu) for lieu in recherche.lieux]
    return "\n".join(entete) + "\n\n" + "\n\n".join(blocs)


def rendre_recherche(recherche: Recherche, sobre: bool) -> str:
    """Un texte par Statut. sobre = sans emoji."""
    match recherche.statut:
        case Statut.OK:
            return _rendre_ok(recherche)
        case Statut.TYPE_MANQUANT:
            return _question(
                "Cherchez-vous une pharmacie, un centre de santé ou une pharmacie de garde ?",
                sobre,
                "🏥",
            )
        case Statut.POSITION_MANQUANTE:
            return _question("Dans quel quartier êtes-vous ?", sobre, "📍")
        case Statut.QUARTIER_INCONNU:
            return "Je ne trouve pas ce quartier.\n" + _question(
                "Pouvez-vous partager votre position ?", sobre, "📍"
            )
        case Statut.AUCUN_LIEU:
            return "Je n'ai trouvé aucun lieu correspondant à cette recherche."
        case _:
            assert_never(recherche.statut)
