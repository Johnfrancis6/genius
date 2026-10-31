
from agent.conversation.graph import build_graph

graphe = build_graph(None, None, None, None, {}, None)  # type: ignore[arg-type]
print(graphe.get_graph().draw_mermaid())