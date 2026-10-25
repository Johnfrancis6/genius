from dataclasses import dataclass

from agent.safety.levels import Level

# Evenement deja interpretter par la coque


@dataclass(frozen=True)
class MessageClasse:
    """ Message utilsateur classe par les regles ou filet llm"""
    niveau: Level
    rule_id:str
    

@dataclass(frozen=True)
class BoutonSigneDanger:
    """  Bouton de question guide """
    question_id : str   #  question identifier pour faire une difference avec ceux de medecin

@dataclass(frozen=True)
class ReevaluationSansDanger:
    """ Retourn rien . Juste pour permettre la descente si  la tables DESCENTE_APRES_REEVALUATION  le permet"""

@dataclass(frozen=True)
class SortieConfirmee:
    """receuil le consentement a travers le bouton  de confirmation du malade. [ peut marcher, a des malaise , cherche un moyen de deplacement]"""
    
    condition: str 
    
    
@dataclass(frozen=True)
class AccuseMedecin:
    """Lorsque le medecin confirme la reception"""
    escalation_id:bool = False


@dataclass(frozen=True)
class DelaiAccuseExpire:
    """ declenche le secon canal ( appel ou sms)"""
    escalation_id:str
    
@dataclass(frozen=True)
class DelaiSecondCanalExpire:
    """ declenche l'avertissement honnete au malade"""
    escalation_id: str 
    
@dataclass(frozen=True)
class AccuseTechnique:
    """  Enregistrer selement => ne ferme jamais l'escalade"""
    escalation_id:str
    
@dataclass(frozen=True)
class EchecEnvoi:
    """  Reprise ou passage anticipe au second canal lorsque le status meta est a failed"""
    escalation_id: str 
    error_code: str
    

Event =  (
          MessageClasse 
          | BoutonSigneDanger 
          | ReevaluationSansDanger 
          | SortieConfirmee 
          | AccuseMedecin 
          | DelaiAccuseExpire
          | DelaiSecondCanalExpire
          | AccuseTechnique 
          | EchecEnvoi)



