"""Tests de la machine à états d'urgence.

Structure actuelle (migration partielle) : SafetyState, EscalationState, DESCENTE_APRES_REEVALUATION
et decide() sont encore dans state_machine.py, et EscalationStatus dans conversation/state.py.

Quand la migration sera terminée, remplacez UNIQUEMENT le bloc « imports dépendant de la structure » par :

    from agent.safety.config import DESCENTE_APRES_REEVALUATION
    from agent.safety.state import EscalationState, EscalationStatus as S, SafetyState
    from agent.safety.state_machine import decide

Les tests décrivent le comportement voulu : un échec signale un défaut du code, pas du test.
"""

import random

# --- imports dépendant de la structure (à modifier à la fin de la migration) ----------
from agent.conversation.state import EscalationStatus as S
from agent.safety.actions import (
    DemarrerEscalade,
    EnregistrerAccuseTechnique,
    EnregistrerSafetyEvent,
    EnvoyerAvertissementHonnete,
    EnvoyerMessageRetourNormal,
    EnvoyerMessageSecurite,
    FermerEscalade,
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
    MessageClasse,
    ReevaluationSansDanger,
    SortieConfirmee,
)
from agent.safety.levels import Level
from agent.safety.state_machine import (
    DESCENTE_APRES_REEVALUATION,
    EscalationState,
    SafetyState,
    decide,
)

# ----------------------------------------------------------------------------------------


def etat(level, statut=None, eid="e1"):
    return SafetyState(level, EscalationState(eid, statut) if statut else None)


def types(d):
    return [type(a) for a in d.actions]


# --- Flux 1 : montée --------------------------------------------------------------------
def test_montee_urgent_depuis_normal():
    d = decide(etat(Level.NORMAL), MessageClasse(Level.URGENT, "r1"))
    assert d.new_state.level == Level.URGENT and not d.refused
    assert types(d) == [EnvoyerMessageSecurite, EnregistrerSafetyEvent, DemarrerEscalade]


def test_pas_de_seconde_escalade():
    d = decide(etat(Level.URGENT, S.MEDECIN_NOTIFIE), MessageClasse(Level.CRITIQUE, "r2"))
    assert d.new_state.level == Level.CRITIQUE
    assert DemarrerEscalade not in types(d)
    assert d.new_state.escalation == EscalationState("e1", S.MEDECIN_NOTIFIE)


def test_incertain_pose_les_questions_sans_escalade():
    d = decide(etat(Level.NORMAL), MessageClasse(Level.INCERTAIN, "r3"))
    assert d.new_state.level == Level.INCERTAIN
    assert types(d) == [PoserQuestionsGuidees, EnregistrerSafetyEvent]


def test_niveau_non_superieur_refuse_sans_action():
    s = etat(Level.URGENT)
    d = decide(s, MessageClasse(Level.INCERTAIN, "r4"))
    assert d.refused and d.actions == () and d.new_state == s


def test_signe_de_danger_monte_a_critique():
    d = decide(etat(Level.NORMAL), BoutonSigneDanger("q1"))
    assert d.new_state.level == Level.CRITIQUE
    assert d.actions[-1] == DemarrerEscalade(Level.CRITIQUE)


def test_rule_id_du_bouton_sans_espace_de_tete():
    d = decide(etat(Level.NORMAL), BoutonSigneDanger("q1"))
    rule_id = next(a for a in d.actions if isinstance(a, EnregistrerSafetyEvent)).rule_id
    assert rule_id == "guided:q1"


# --- Flux 2 : accusé du médecin ----------------------------------------------------------
def test_accuse_ferme_escalade_ouverte():
    d = decide(etat(Level.URGENT, S.MEDECIN_NOTIFIE), AccuseMedecin("e1"))
    assert not d.refused and d.new_state.escalation.status is S.ACCUSEE
    assert FermerEscalade in types(d)


def test_accuse_depuis_second_canal_ferme_aussi():
    d = decide(etat(Level.URGENT, S.SECOND_CANAL), AccuseMedecin("e1"))
    assert not d.refused and d.new_state.escalation.status is S.ACCUSEE


def test_double_accuse_refuse():
    s = etat(Level.URGENT, S.ACCUSEE)
    d = decide(s, AccuseMedecin("e1"))
    assert d.refused and d.actions == () and d.new_state == s


def test_accuse_escalade_inconnue_refuse():
    d = decide(etat(Level.URGENT, S.MEDECIN_NOTIFIE), AccuseMedecin("autre"))
    assert d.refused and d.actions == ()


def test_accuse_sans_escalade_refuse():
    assert decide(etat(Level.URGENT), AccuseMedecin("e1")).refused


# --- Flux 3 : minuteries -------------------------------------------------------------------
def test_minuterie_apres_accuse_refusee():
    s = etat(Level.URGENT, S.ACCUSEE)
    for evt in (DelaiAccuseExpire("e1"), DelaiSecondCanalExpire("e1")):
        d = decide(s, evt)
        assert d.refused and d.actions == ()


def test_second_canal_puis_avertissement_dans_l_ordre():
    d1 = decide(etat(Level.CRITIQUE, S.MEDECIN_NOTIFIE), DelaiAccuseExpire("e1"))
    assert NotifierSecondCanal in types(d1) and d1.new_state.escalation.status is S.SECOND_CANAL
    d2 = decide(d1.new_state, DelaiSecondCanalExpire("e1"))
    assert EnvoyerAvertissementHonnete in types(d2)
    assert d2.new_state.escalation.status is S.SANS_REPONSE


def test_delai_accuse_programme_la_prochaine_etape():
    d = decide(etat(Level.CRITIQUE, S.MEDECIN_NOTIFIE), DelaiAccuseExpire("e1"))
    etapes = [a for a in d.actions if isinstance(a, ProgrammerEtape)]
    assert len(etapes) == 1 and etapes[0].escalation_id == "e1"


def test_avertissement_refuse_sans_passer_par_le_second_canal():
    d = decide(etat(Level.CRITIQUE, S.MEDECIN_NOTIFIE), DelaiSecondCanalExpire("e1"))
    assert d.refused and EnvoyerAvertissementHonnete not in types(d)


def test_minuterie_d_une_autre_escalade_refusee():
    d = decide(etat(Level.CRITIQUE, S.MEDECIN_NOTIFIE), DelaiAccuseExpire("e2"))
    assert d.refused and d.actions == ()


# --- Flux 4 : suivi technique ----------------------------------------------------------------
def test_accuse_technique_enregistre_sans_fermer():
    s = etat(Level.URGENT, S.MEDECIN_NOTIFIE)
    d = decide(s, AccuseTechnique("e1"))
    assert types(d) == [EnregistrerAccuseTechnique] and d.new_state == s
    assert FermerEscalade not in types(d)


def test_accuse_technique_escalade_inconnue_refuse():
    d = decide(etat(Level.URGENT), AccuseTechnique("e1"))
    assert d.refused and d.reason == "escalade_inconnue"


def test_echec_envoi_relance_si_en_attente():
    d = decide(etat(Level.URGENT, S.MEDECIN_NOTIFIE), EchecEnvoi("e1", "131000"))
    assert types(d) == [RelancerEnvoi] and not d.refused


def test_echec_envoi_apres_accuse_refuse():
    d = decide(etat(Level.URGENT, S.ACCUSEE), EchecEnvoi("e1", "131000"))
    assert d.refused and d.actions == ()


# --- Flux 5 : descente --------------------------------------------------------------------------
def test_reevaluation_critique_descend_a_urgent_sans_message_retour_normal():
    d = decide(etat(Level.CRITIQUE), ReevaluationSansDanger())
    assert d.new_state.level == Level.URGENT and not d.refused
    assert types(d) == [EnregistrerSafetyEvent]


def test_reevaluation_incertain_descend_a_normal_avec_message():
    d = decide(etat(Level.INCERTAIN), ReevaluationSansDanger())
    assert d.new_state.level == Level.NORMAL
    assert types(d) == [EnregistrerSafetyEvent, EnvoyerMessageRetourNormal]


def test_reevaluation_refusee_si_niveau_absent_de_la_table():
    for niveau in (Level.NORMAL, Level.URGENT):
        s = etat(niveau)
        d = decide(s, ReevaluationSansDanger())
        assert d.refused and d.actions == () and d.new_state == s


def test_descente_conserve_l_escalade():
    d = decide(etat(Level.CRITIQUE, S.MEDECIN_NOTIFIE), ReevaluationSansDanger())
    assert d.new_state.escalation == EscalationState("e1", S.MEDECIN_NOTIFIE)


# --- Flux 6 : refus ---------------------------------------------------------------------------------
def test_sortie_confirmee_pas_encore_implementee():
    d = decide(etat(Level.URGENT), SortieConfirmee("engin"))
    assert d.refused and d.reason == "non_implemente"


def test_evenement_inconnu_refuse():
    d = decide(etat(Level.NORMAL), "n'importe quoi")
    assert d.refused and d.reason == "evenement_inconnu"


def test_decide_ne_renvoie_jamais_none():
    for evt in _evenements_possibles():
        for niveau in Level:
            for statut in (None, *S):
                assert decide(etat(niveau, statut), evt) is not None


# --- Invariants sur des suites aléatoires (version sans Hypothesis) ------------------------------------
def _evenements_possibles():
    evts = [MessageClasse(n, "r") for n in Level]
    evts += [BoutonSigneDanger("q"), ReevaluationSansDanger(), SortieConfirmee("engin")]
    for eid in ("e1", "e2"):
        evts += [
            AccuseMedecin(eid), DelaiAccuseExpire(eid), DelaiSecondCanalExpire(eid),
            AccuseTechnique(eid), EchecEnvoi(eid, "131000"),
        ]
    return evts


def test_invariants_sur_suites_aleatoires():
    rng = random.Random(42)
    evts = _evenements_possibles()
    for _ in range(300):
        s = etat(rng.choice(list(Level)), rng.choice([None, *S]))
        for _ in range(30):
            e = rng.choice(evts)
            d = decide(s, e)
            if d.new_state.level < s.level:  # seule une réévaluation, via la table, fait descendre
                assert isinstance(e, ReevaluationSansDanger)
                assert d.new_state.level == DESCENTE_APRES_REEVALUATION[s.level]
            if d.refused:
                assert d.new_state == s and d.actions == ()
            if FermerEscalade in types(d):
                assert isinstance(e, AccuseMedecin), "seul l'accusé humain ferme l'escalade"
            if s.escalation and s.escalation.status is S.ACCUSEE:
                assert d.new_state.escalation == s.escalation, "ACCUSEE est terminal"
            s = d.new_state