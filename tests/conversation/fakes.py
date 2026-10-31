"""Faux LLM pour les tests des nœuds."""

from __future__ import annotations


class FauxLLM:
    """Rejoue des réponses dans l'ordre (la dernière se répète). Une exception est levée."""

    def __init__(self, *reponses):
        self._reponses = list(reponses)
        self.appels: list[dict] = []

    async def __call__(
        self, messages, model=None, json_mode=False, temperature=None, max_tokens=1024
    ):
        self.appels.append(
            {
                "messages": list(messages),
                "model": model,
                "json_mode": json_mode,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        r = self._reponses.pop(0) if len(self._reponses) > 1 else self._reponses[0]
        if isinstance(r, BaseException):
            raise r
        return r
