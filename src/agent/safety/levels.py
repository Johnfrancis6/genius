# On traite le malade au niveau urgent tant que non preciser


# Systeme de scoring d'urgence  contient les fonctions necessaires pour le calcule du niveau d'urgence



from enum import IntEnum


class Level(IntEnum):
    """ chaque niveau se situe dans une plage"""
    NORMAL = 1
    INCERTAIN = 2
    URGENT = 3
    CRITIQUE = 4
    

#  comparaison d'un ensemble de nivaeu differents avec le level par defaut

def worst(*levels: Level)-> Level:
    """  recoi une liste et compaire l'element le plus eleve a la valeur par defaut"""
    return max(levels, default=Level.NORMAL)


# Mis en place d'un filet llm . On ecarte les cas ou l'evaluation du llm tend vers la baisse
def raise_only (current :Level, proposed:Level)-> Level:
    """ Compare l'etat actuel a une proposition du llm. Mais garde la proposition la plus critique"""
    return max(current, proposed)


def is_emergency(level:Level)-> bool:
    """ valeur boolenne => filtrage urgence """
    return level>=Level.INCERTAIN





