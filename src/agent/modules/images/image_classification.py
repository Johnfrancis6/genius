import json
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.core.prompt import CLASSIFICATION_PROMPT

from .image_data import (
    Accepte,
    Call_VLM,
    Lisibilite,
    ReasonRejet,
    Reject,
    Resultat,
    TypeImage,
    extraction,
)
from .json_utils import extraire_json

MAX_DESCRIPTION = 200


logger = logging.getLogger(__name__)





class Classification_output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    
    type : TypeImage
    lisibilite : Lisibilite
    signe_medical_visible: bool = False
    description: str = Field(default="", max_length=MAX_DESCRIPTION, repr=False)
    


async def   classifier(image:bytes, appel:Call_VLM)-> Resultat[Classification_output]:
    
    return await  extraction(image, CLASSIFICATION_PROMPT, appel,valider)



def valider(brut:str)-> Resultat[Classification_output]:
    

    try: 
        data =  json.loads(extraire_json(brut))
    except json.JSONDecodeError  :
        return  Reject(ReasonRejet.JSON_INVALIDE, retryable=True)
    
    
    try :
        out = Classification_output.model_validate(data)
    except  ValidationError  as e :
        if any(err["type"]== "extra_forbidden"  for err  in e.errors()):
           logger.warning("Extraction rejetée : %s (réessayable=%s)", ReasonRejet.CHAMP_INTERDIT, False)
           return Reject(ReasonRejet.CHAMP_INTERDIT, retryable=False)
        logger.warning("Extraction rejetée : %s (réessayable=%s)", ReasonRejet.SCHEMA_INVALIDE, True)
        return  Reject(ReasonRejet.SCHEMA_INVALIDE, retryable= True)
    
    
    return  Accepte(out)