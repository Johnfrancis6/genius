import pytest

from agent.core import llm


async def test_faux_llm_rejoue_dans_l_ordre(faux_llm):
    faux = faux_llm('{"a": 1}', "deuxieme")
    msgs = [{"role": "user", "content": "json"}]
    assert await llm.complete_text(msgs, json_mode=True) == '{"a": 1}'
    assert await llm.complete_text(msgs) == "deuxieme"
    assert await llm.complete_text(msgs) == "deuxieme"  # la dernière se répète
    assert [a["json_mode"] for a in faux.appels] == [True, False, False]


async def test_faux_llm_leve_une_exception(faux_llm):
    faux_llm(llm.LLMError("x"))
    with pytest.raises(llm.LLMError):
        await llm.complete_text([{"role": "user", "content": "a"}])
