import pytest

from agent.core import llm

from .fakes import FauxLLM


@pytest.fixture
def faux_llm(monkeypatch):
    """faux = faux_llm('rep1', 'rep2', LLMError('x')) remplace llm.complete_text."""

    def installer(*reponses):
        faux = FauxLLM(*reponses)
        monkeypatch.setattr(llm, "complete_text", faux)
        return faux

    return installer
