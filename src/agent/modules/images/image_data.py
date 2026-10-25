from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from agent.modules.images.json_utils import extraire_json

logger = logging.getLogger(__name__)


ILLISIBLE = "[illisible]"
MASQUE = "[masqué]"
MAX_TEXTE = 300

Certitude = Literal["haute", "moyenne", "basse"]
Lisibilite = Literal["bonne", "partielle", "mauvaise"]
TypeImage = Literal["ordonnance", "piece_identite", "autre", "illisible"]

#=========================
# Piece d'identite 
#=========================

class Extracted_field(BaseModel):
    """Structure  globale des donnees extraites   """
    value: str | None = Field(default=None, repr=False)
    confident: Certitude | None = None
    
    @model_validator(mode="after")
    def bad_doc_quality(self):
        if self.value ==  ILLISIBLE  and self.confident != "basse" :
            raise ValueError("[ILLISIBLE]  exige certitude 'basse' ")
        return self
    

    
    
class IdCardFields(BaseModel):
    """ Data field from individual id card """
    model_config = ConfigDict(extra="forbid")
    
    field_name : Extracted_field = Field(default_factory=Extracted_field)
    born_on :Extracted_field = Field(default_factory=Extracted_field)
    sexe : Extracted_field = Field(default_factory=Extracted_field)
    create_on : Extracted_field = Field(default_factory=Extracted_field)
    expire_on: Extracted_field = Field(default_factory=Extracted_field)
    identity_ID: Extracted_field = Field(default_factory=Extracted_field)
    nationality:Extracted_field = Field(default_factory=Extracted_field)
    place_of_birth:Extracted_field= Field(default_factory=Extracted_field)
    size: Extracted_field = Field(default_factory=Extracted_field)
    country: Extracted_field = Field(default_factory=Extracted_field)
    
    
#=========================
# Ordonnance
#=========================


class Drug(BaseModel):
    model_config  = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_TEXTE, repr=False)
    confident: Certitude

    @model_validator(mode="after")
    def illisible_implique_basse(self):
           if ILLISIBLE in self.text and self.confident != "basse":
               raise ValueError("[illisible] exige certitude 'basse'")
           return self
    

class Ordonnance_output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type:Literal["ordonnance"]
    lisibilite: Lisibilite
    lignes : list[Drug] = Field(default_factory=list)
    medicaments_ecrits : list[Drug] = Field(default_factory=list)
    signe_medical_visible: bool = False
        
        
#======================
# Global
#======================

class ReasonRejet(StrEnum):
    JSON_INVALIDE = "json_invalide"
    SCHEMA_INVALIDE = "schema_invalide"
    MEDICAMENT_ABSENT = "medicament_absent_des_lignes"
    TAILLE_EXCESSIVE = "taille_excessive"
    CHAMP_INTERDIT = "champ_interdit"
    SIGNE_MEDICAL = "signe_medical_visible"
    IMAGE_INVALIDE = "image_invalide" 
    ERREUR_FOURNISSEUR = "erreur_fournisseur"
    

@dataclass(frozen=True)
class Accepte[T]:
    output: T = field(repr=False)

@dataclass(frozen=True)
class Reject:
    reason: ReasonRejet
    retryable : bool = False


type Resultat[T] = Accepte[T] | Reject
Call_VLM = Callable[[bytes, str], Awaitable[str]]


async def extraction[M](image : bytes, prompt: str , appel: Call_VLM, valider: Callable[[str], Resultat[M]])-> Resultat[M]:
      """  fonction asynchrone faire un appel groq et extrire les donnees  necessaires"""
      for  tentative in (1,2):
            try: 
                brut = await  appel(image, prompt)
            except  Exception as e:
                logger.warning("Appel VLM échoué [tentative %d] : %s", tentative, type(e).__name__)
                return Reject(ReasonRejet.ERREUR_FOURNISSEUR)
            res = valider(brut)
            
            
            if isinstance(res, Accepte)  or not res.retryable:
                return res
            
            logger.info(" Sortie rejettee (%s),  tentatives %d", res.reason, tentative)
            
      return  res
  
  
  
MAX_BRUT = 20_000  # point de départ, à ajuster sur de vraies réponses

def parse_modele[M: BaseModel](brut: str, modele: type[M]) -> M | Reject:
    """Texte brut du VLM -> instance validée, ou Reject.
    
    1. len(brut) > MAX_BRUT                -> Reject(TAILLE_EXCESSIVE, retryable=True)
    2. json.loads(extraire_json(brut))     -> Reject(JSON_INVALIDE, retryable=True)
    3. modele.model_validate(data), erreurs ValidationError :
       - une erreur de type "extra_forbidden"            -> Reject(CHAMP_INTERDIT, retryable=False)  (testé en premier)
       - une erreur "string_too_long" ou "too_long"      -> Reject(TAILLE_EXCESSIVE, retryable=True)
       - autre                                           -> Reject(SCHEMA_INVALIDE, retryable=True)
    Log : seulement la raison et retryable. Jamais str(e), jamais le texte du VLM.
    """
    
    if len(brut)> MAX_BRUT:
        return Reject(ReasonRejet.TAILLE_EXCESSIVE, retryable=True)
    
    try:
        data =  json.loads(extraire_json(brut))
    except json.JSONDecodeError  :
        return  Reject(ReasonRejet.JSON_INVALIDE, retryable=True)
    
    try:
        out = modele.model_validate(data)
    except ValidationError as e:
        types = {err["type"] for err in e.errors()}
        if "extra_forbidden" in types:
            raison, retry = ReasonRejet.CHAMP_INTERDIT, False
        elif types & {"string_too_long", "too_long"}:
            raison, retry = ReasonRejet.TAILLE_EXCESSIVE, True
        else:
            raison, retry = ReasonRejet.SCHEMA_INVALIDE, True
        logger.warning("Extraction rejetée : %s (réessayable=%s)", raison, retry)
        return Reject(raison, retryable=retry)

    return out

