from usta import anayasa
from usta.agent import SYSTEM_PROMPT


def test_principles_are_added_only_when_switched_on(monkeypatch):
    monkeypatch.delenv("USTA_ANAYASA", raising=False)
    assert anayasa.system_prompt(SYSTEM_PROMPT) == SYSTEM_PROMPT
    monkeypatch.setenv("USTA_ANAYASA", "1")
    full = anayasa.system_prompt(SYSTEM_PROMPT)
    assert full.startswith(SYSTEM_PROMPT) and "zararlı yazılım" in full and "Dürüst ol" in full


def test_principles_stay_small_for_small_models():
    # 16k bağlamlı küçük modelde görev ve dosyalara yer kalsın
    assert len(anayasa.ILKELER) < 1500
