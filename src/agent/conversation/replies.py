"""Textes fixes de l'agent : vouvoiement, format WhatsApp.

Les numéros d'urgence viennent de EMERGENCY_NUMBERS : aucun n'est écrit en dur ici.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from agent.settings import get_setting

logger = logging.getLogger(__name__)

CLE_ERREUR = "probleme_technique"

_TEXTES: dict[str, str] = {
    "audio_bientot": (
        "Merci pour votre message vocal. Je ne peux pas encore écouter les vocaux, "
        "mais cette fonction arrive bientôt. Pouvez-vous m'écrire votre message "
        "en quelques mots ?"
    ),
    "clarif_choice": (
        "Pouvez-vous vous déplacer jusqu'à un centre de santé, ou avez-vous "
        "besoin d'aide pour vous y rendre ?"
    ),
        "clarif_kind": (
        "De quel type de lieu avez-vous besoin : une pharmacie, un centre de santé "
        "ou une pharmacie de garde ?"
    ),
    "clarif_free_text": "Pouvez-vous m'expliquer en quelques mots ce qui se passe ?",
    "clarif_location": (
        "Dans quel quartier êtes-vous ? Vous pouvez aussi m'envoyer votre position."
    ),
    "clarif_image": "Pouvez-vous m'envoyer une photo de votre pièce d'identité ?",
    "type_non_gere": (
        "Je ne peux pas lire ce type de message pour le moment. "
        "Pouvez-vous m'écrire votre demande, ou m'envoyer une photo ?"
    ),
    "image_a_renvoyer": (
        "📄 Je n'arrive pas à utiliser cette image. Pouvez-vous la renvoyer en photo "
        "nette, bien éclairée, avec le document entier visible ?"
    ),
    "clarif_confirm": "Pouvez-vous me répondre par oui ou par non ?",
    CLE_ERREUR: (
        "Désolé, j'ai un problème technique. Pouvez-vous réessayer dans quelques instants ?"
    ),
    "hors_perimetre": (
        "Je ne peux pas vous aider pour cette demande. Je suis Genius : je vous aide "
        "à trouver un centre de santé ou une pharmacie, un moyen de vous déplacer, "
        "ou à joindre un professionnel de santé.\n"
        "Vous pouvez par exemple écrire :\n"
        "• « Je cherche une pharmacie de garde »\n"
        "• « Je ne peux pas me déplacer, j'ai besoin d'aide pour aller au centre de santé »"
    ),
    "aide_humaine": (
        "🤝 Je comprends que vous souhaitez parler à une personne. Ce service n'est pas "
        "encore disponible. En attendant, dites-moi ce dont vous avez besoin et "
        "j'essaie de vous aider."
    ),
        "menu_accueil": (
        "Bonjour, je suis Genius 🤝. Je vous aide à trouver un centre de santé ou "
        "une pharmacie, ou à vous déplacer. Que souhaitez-vous faire ?"
    ),
    "menu_rappel": "Que souhaitez-vous faire ?",
    "menu_autre": "D'accord. Dites-moi en quelques mots ce dont vous avez besoin.",
    "urgence": (
        "🚨 *Votre situation semble urgente.*\n"
        "Appelez tout de suite :\n{numeros}\n"
        "Si vous ne pouvez pas appeler, demandez à une personne près de vous de le faire, "
        "ou rendez-vous aux urgences les plus proches."
    ),
    "urgence_sans_numero": (
        "🚨 *Votre situation semble urgente.*\n"
        "Rendez-vous tout de suite aux urgences du centre de santé le plus proche, "
        "ou demandez à une personne près de vous de vous y emmener ou d'appeler les secours."
    ),
    "urgence_numeros": (
        "Par précaution, voici les numéros d'urgence :\n{numeros}\n"
        "Appelez-les sans attendre si la situation s'aggrave."
    ),
}


def _numeros_urgence() -> list[str]:
    """Numéros configurés. Réglages illisibles : liste vide (le message générique reste sûr)."""
    try:
        return [n.strip() for n in get_setting().EMERGENCY_NUMBERS if n.strip()]
    except Exception as e:
        logger.warning("Numéros d'urgence illisibles exc=%s", type(e).__name__)
        return []


def verifier_numeros_urgence() -> bool:
    """À appeler au démarrage (lifespan). Journalise un avertissement si la liste est vide."""
    present = bool(_numeros_urgence())
    if not present:
        logger.warning("EMERGENCY_NUMBERS vide : les messages d'urgence seront sans numéro")
    return present


def render_reply(key: str, args: Mapping[str, str] | None = None) -> str:
    """Texte fixe pour `key`. Clé inconnue ou paramètre manquant : message d'erreur technique.

    `urgence_numeros` renvoie une chaîne vide si aucun numéro n'est configuré :
    l'appelant l'ajoute en préfixe et doit gérer ce cas.
    """
    valeurs: dict[str, str] = dict(args or {})

    if key in ("urgence", "urgence_numeros"):
        numeros = _numeros_urgence()
        if not numeros:
            if key == "urgence_numeros":
                return ""
            key = "urgence_sans_numero"
        else:
            valeurs["numeros"] = "\n".join(f"• {n}" for n in numeros)

    modele = _TEXTES.get(key)
    if modele is None:
        logger.warning("render_reply : clé inconnue %s", key[:40])
        return _TEXTES[CLE_ERREUR]
    try:
        return modele.format_map(valeurs)
    except (KeyError, IndexError, ValueError):
        logger.warning("render_reply : paramètre manquant pour %s", key)
        return _TEXTES[CLE_ERREUR]


MOTIF_DEFAUT = "vous orienter au plus près"
MOTIFS_LOCALISATION: dict[str, str] = {
    "transport": "organiser votre transport",
    "pharmacie": "chercher une pharmacie proche",
    "pharmacie de garde": "chercher une pharmacie de garde proche",
    "centre de santé": "trouver un centre de santé proche",
    "garde": "trouver un service de garde proche",
    "médecin": "trouver un médecin proche",
    "pharmacy": "chercher une pharmacie proche",
    "health_center": "trouver un centre de santé proche",
    "on_call": "chercher une pharmacie de garde proche",
} # clé = kind ou intent -> but ; une ligne par service livré


def texte_localisation(intent: str | None, kind: str | None, sobre: bool) -> str:
    """Priorité : kind, puis intent, puis MOTIF_DEFAUT. Sobre : sans emoji."""
    motif = MOTIF_DEFAUT
    for cle in (kind, intent):
        if cle and (trouve := MOTIFS_LOCALISATION.get(cle.strip().casefold())):
            motif = trouve
            break
    emoji = "" if sobre else " 📍"
    return (
        f"Nous avons besoin de votre localisation pour {motif}.\n"
        f"Pouvez-vous partager votre position ?{emoji}"
    )


# Source unique : le repli « clarif_location » reprend le texte par défaut.
_TEXTES["clarif_location"] = texte_localisation(None, None, False)
