from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.conversation.format_whatsapp import normaliser_pour_whatsapp
from agent.conversation.nodes import (
    apres_clarificateur,
    apres_route,
    creer_noeud_clarificateur,
    creer_noeud_genius,
    creer_noeud_lieux,
    creer_noeud_route,
    creer_noeud_stock,
    creer_noeud_traiter_image,
    suite_ou_fin,
    transcrire,
    urgence,
)
from agent.conversation.replies import render_reply
from agent.conversation.state import ConversationState
from agent.modules.images.image_data import Call_VLM, TypeImage
from agent.modules.images.image_tool import Extracteur
from agent.safety.levels import Level
from agent.stores import ExtractionStore, MessageStore, PgImageStore

# CompiledStateGraph : paramètres génériques non confirmés pour LangGraph 1.2.16
Graphe = Any


def build_graph(
    images: PgImageStore,
    resultats: ExtractionStore,
    messages: MessageStore,
    appel: Call_VLM,
    extracteurs: dict[TypeImage, Extracteur],
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Graphe:
    """Compile le graphe V1 (à appeler une seule fois, au démarrage)."""
    g = StateGraph(ConversationState)
    g.add_node("transcrire", transcrire)
    g.add_node("urgence", urgence)
    g.add_node(
        "traiter_image",
        creer_noeud_traiter_image(images, resultats, appel, extracteurs),
    )
    g.add_node("route", creer_noeud_route(messages))
    g.add_node("clarificateur", creer_noeud_clarificateur(messages))
    g.add_node("genius", creer_noeud_genius(messages))
    g.add_node("lieux", creer_noeud_lieux(sessionmaker))
    g.add_node("stock", creer_noeud_stock(sessionmaker))
    g.add_edge("stock", END)
    g.add_edge(START, "transcrire")
    g.add_conditional_edges("transcrire", suite_ou_fin, {"suite": "urgence", "fin": END})
    g.add_conditional_edges("urgence", suite_ou_fin, {"suite": "traiter_image", "fin": END})
    g.add_edge("traiter_image", "route")
    g.add_conditional_edges(
        "route",
        apres_route,
        {"fin": END, "clarificateur": "clarificateur", "lieux": "lieux", "genius": "genius"},
    )
    g.add_conditional_edges(
        "clarificateur",
        apres_clarificateur,
        {"lieux": "lieux", "stock": "stock", "genius": "genius", "fin": END},
    )
    g.add_edge("lieux", END)
    g.add_edge("genius", END)
    return g.compile()


async def run_graph(graphe: Graphe, state: ConversationState) -> tuple[str, dict[str, Any]]:
    """Exécute un tour. Retourne (réponse, état final).

    Le store filtre lui-même sur PERSISTED_KEYS. Une exception du graphe n'est pas
    attrapée : le webhook envoie le message de repli sans sauver l'état.
    """
    final: dict[str, Any] = await graphe.ainvoke(state)

    if final["reply_key"]:
        texte = render_reply(final["reply_key"], final["reply_args"])
    else:
        sobre = Level(final["urgency_level"]).value >= Level.INCERTAIN.value
        texte = normaliser_pour_whatsapp(final["reply_text"] or "", sobre=sobre)
        texte = texte or render_reply("probleme_technique")
    # INCERTAIN : numéros d'urgence en préfixe, le tour a continué normalement.
    if Level(final["urgency_level"]) == Level.INCERTAIN:
        numeros = render_reply("urgence_numeros")
        if numeros:
            texte = f"{numeros}\n\n{texte}"
    return texte, final
