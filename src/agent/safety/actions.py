from dataclasses import dataclass

from agent.safety.levels import Level


@dataclass(frozen=True)
class EnregistrerSafetyEvent:
    """declenche par tout changement de niveau"""

    niveau: Level
    rule_id: str | None = None
    resolution: str | None = None


@dataclass(frozen=True)
class EnvoyerMessageSecurite:
    """Montee de niveau"""

    niveau: Level


@dataclass(frozen=True)
class DemarrerEscalade:
    """Momter a urgent ou plus"""

    niveau: Level


@dataclass(frozen=True)
class PoserQuestionsGuidees:
    """declenchee par incertain ou besoin de reevaluation"""

    arbre_id: str


@dataclass(frozen=True)
class DemanderConfirmationSortie:
    """si Niveau faible ou debut de  sortie =>  bouton de confirmation"""

    condition: str


@dataclass(frozen=True)
class EnvoyerMessageRetourNormal:
    """decente de niveau , ne retoutrne rien"""


@dataclass(frozen=True)
class ConfirmerAlerteAUtilisateur:
    """[ declenche par accuse medecin uniquement] Informe au malade la reception du message par un medecin"""

    escalation_id: str


@dataclass(frozen=True)
class FermerEscalade:
    """[ declenche par accuse medecin uniquement]  => acked_at reseigner"""

    escalation_id: str


@dataclass(frozen=True)
class NotifierMedecin:
    """[declenchee par DemarrerEscalade]. 	template WhatsApp avec bouton  Recu"""

    escalation_id: str
    medecin_id: str


@dataclass(frozen=True)
class ProgrammerEtape:
    """[declenche par envoi au medecin ou second canal] le planifier rempli chaque minutes"""

    escalation_id: str
    delai_secondes: int


@dataclass(frozen=True)
class NotifierSecondCanal:
    """appel"""

    escalation_id: str


@dataclass(frozen=True)
class EnvoyerAvertissementHonnete:
    """message avec numero d'urgence"""

    escalation_id: str


@dataclass(frozen=True)
class EnregistrerAccuseTechnique:
    """delivered_at  reseigner sans fermer l'excalade"""

    escalation_id: str


@dataclass(frozen=True)
class RelancerEnvoi:
    """reprise ou second canal anticiper"""

    escalation_id: str


@dataclass(frozen=True)
class EnvoyerBoutonEstCeUrgent:
    """[vocal recur] => message de securite plus bouton"""


@dataclass(frozen=True)
class DemanderPrecisionTexte:
    """[image  recu] 	demande de precision par text"""


@dataclass(frozen=True)
class JournaliserAudit:
    """Journalisation"""

    action: str
    # sujet_hash:str


Action = (
    EnregistrerSafetyEvent
    | EnvoyerMessageSecurite
    | DemarrerEscalade
    | PoserQuestionsGuidees
    | DemanderConfirmationSortie
    | EnvoyerMessageRetourNormal
    | ConfirmerAlerteAUtilisateur
    | FermerEscalade
    | NotifierMedecin
    | ProgrammerEtape
    | NotifierSecondCanal
    | EnvoyerAvertissementHonnete
    | EnregistrerAccuseTechnique
    | RelancerEnvoi
    | EnvoyerBoutonEstCeUrgent
    | DemanderPrecisionTexte
    | JournaliserAudit
)
