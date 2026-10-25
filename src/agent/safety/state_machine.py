from __future__ import annotations

from dataclasses import dataclass

from agent.conversation.state import EscalationStatus
from agent.safety.actions import (
    Action,
    ConfirmerAlerteAUtilisateur,
    DemarrerEscalade,
    EnregistrerAccuseTechnique,
    EnregistrerSafetyEvent,
    EnvoyerAvertissementHonnete,
    EnvoyerMessageRetourNormal,
    EnvoyerMessageSecurite,
    FermerEscalade,
    JournaliserAudit,
    NotifierSecondCanal,
    PoserQuestionsGuidees,
    ProgrammerEtape,
    RelancerEnvoi,
)
from agent.safety.events import (
    AccuseMedecin,
    AccuseTechnique,
    BoutonSigneDanger,
    DelaiAccuseExpire,
    DelaiSecondCanalExpire,
    EchecEnvoi,
    Event,
    MessageClasse,
    ReevaluationSansDanger,
    SortieConfirmee,
)
from agent.safety.levels import Level

SEUIL_ESCALADE = Level.URGENT 
ARBRE_PAR_DEFAUT = "signes_danger_v1" 
NIVEAU_SIGNE_DANGER = Level.CRITIQUE
DELAI_SECOND_CANAL_S = 300 
DELAI_AVERTISSEMENT_S = 300




@dataclass(frozen=True)
class Decision : 
    new_state: SafetyState
    actions : tuple[Action, ...] =()
    refused: bool= False   # facultatif
    reason: str | None = None

#  le level n'implement des solution pour hausser le niveau  


def _monter(state:SafetyState,  cible :Level, rule_id:str|None)-> Decision:
    """ Monter toujours accepter si la cible depasse le niveau"""
    if cible <= state.level:
        return _refuser(state, "niveau_non_superieur")
    actions  : list[Action] = []
    
    
    if cible == Level.INCERTAIN:
        actions.append(PoserQuestionsGuidees(arbre_id=ARBRE_PAR_DEFAUT))
    
    else: 
        actions.append(EnvoyerMessageSecurite(niveau=cible))
    actions.append(EnregistrerSafetyEvent(niveau=cible, rule_id=rule_id))
    
    
    if state.level < SEUIL_ESCALADE <= cible:
        actions.append(DemarrerEscalade(niveau=cible))
    return Decision(SafetyState(cible, state.escalation), tuple(actions))

# implementation de la descente authoriser par une reevaluation sans danger : start -> end 

DESCENTE_APRES_REEVALUATION: dict[Level, Level] = {
    Level.CRITIQUE : Level.URGENT ,
    Level.INCERTAIN : Level.NORMAL ,
}


# Fonction centrale du block   => decide les actions a effectuer selon le niveau du malade et l'evenement  enregistrer|   serie de condtion match   selon l'event

#  Priorites  en 03  temps :
# - Ordre des cas des conditions : ce qui peut augement (niveau)  est traite d'abord  avant les baisssiers
# - ce qui n'est jamais bloquer : une monte ne depend d'aucune garde
# - Ordre des actions dans une decision : => user first 


@dataclass(frozen=True)
class EscalationState:
    escalation_id : str
    status : EscalationStatus
    
@dataclass(frozen=True)
class SafetyState:
    level: Level
    escalation: EscalationStatus | None =None
    

def _statut(state: SafetyState, escalation_id: str) -> EscalationState | None:
    e = state.escalation
    return e.status if e and e.escalation_id == escalation_id else None

def _refuser(state: SafetyState, reason: str) -> Decision:
    return Decision(state, refused=True, reason=reason)

def _avec_statut(state: SafetyState, eid: str, statut: EscalationStatus) -> SafetyState:
    return SafetyState(state.level, EscalationState(eid, statut))



# status ou l'on attend encore l'accuser humain


EN_ATTENTE = frozenset({EscalationStatus.MEDECIN_NOTIFIE, EscalationStatus.SECOND_CANAL})


def decide(state:SafetyState,  event:Event)-> Decision:
        match event: 
            case MessageClasse(niveau=n, rule_id=rid):
                return _monter(state, n, rid)
               
                
            case BoutonSigneDanger(question_id=qid):
                return _monter(state, NIVEAU_SIGNE_DANGER, f"guided:{qid}" )
             
            case AccuseMedecin  (escalation_id= eid) :
                if  _statut(state, eid)  not in (  EscalationStatus.MEDECIN_NOTIFIE, EscalationStatus.SECOND_CANAL):
                    return  _refuser(state, "escalade_non_en_attente")
                return Decision(_avec_statut(state, eid, EscalationStatus.ACCUSEE),
                                (FermerEscalade(eid),
                                 ConfirmerAlerteAUtilisateur(eid),
                                 EnregistrerSafetyEvent(state.level, resolution="accuse_medecin"),),)
            case DelaiAccuseExpire(escalation_id=eid):
                if _statut(state, eid)  is not EscalationStatus.MEDECIN_NOTIFIE:
                    return _refuser(state, "minuterie_perimee")
                return  Decision(_avec_statut(state, eid, EscalationStatus.SECOND_CANAL),
                                 (
                                     NotifierSecondCanal(eid), 
                                     ProgrammerEtape(eid, delai_secon=DELAI_AVERTISSEMENT_S)
                                 ))
                
                
                
            
            case DelaiSecondCanalExpire(escalation_id=eid):
                if _statut(state, eid) is not EscalationStatus.SECOND_CANAL:
                    return _refuser(state, "minuterie_perimee")
                return  Decision(
                    _avec_statut(state, eid, EscalationStatus.SANS_REPONSE),
                    (
                        EnvoyerAvertissementHonnete(eid),
                        EnregistrerSafetyEvent(state.level, resolution="sans_accuse"),
                        JournaliserAudit("avertissement_honnete_envoye"),
                    )
                )
            
              
            
            
            # flux 4
            
            
            case AccuseTechnique(escalation_id=technique):
                if _statut(state, technique)  is None:
                    return _refuser(state, "escalade_inconnue")

                return  Decision(state, (EnregistrerAccuseTechnique(technique),))
            
            case EchecEnvoi(escalation_id=technique_echec ):
                 if _statut(state, technique_echec) not in EN_ATTENTE:
                     return  _refuser(state , "escalade_non_en_attente")
                 return Decision(state, (RelancerEnvoi(technique_echec),))
                     
                     
        
            
            # flux 5 
            case ReevaluationSansDanger():
                cible = DESCENTE_APRES_REEVALUATION.get(state.level)
                if cible is None:
                    return _refuser(state, "descente_non_authorisee")
                actions: list[Action] = [
                      EnregistrerSafetyEvent(niveau=cible, resolution="reevaluation_sans_danger")
                ]  
                if cible ==  Level.NORMAL: 
                    actions.append(EnvoyerMessageRetourNormal()) 
                return Decision(SafetyState(cible, state.escalation), tuple(actions), reason="non_implementer") 
                               
            case SortieConfirmee():
                return _refuser(state, "non_implemente")
            
            case _ :
                return Decision(state , refused=True, reason ="evenement_inconnu")
            
            