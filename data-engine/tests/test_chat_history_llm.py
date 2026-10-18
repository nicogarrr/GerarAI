"""El historial llega acotado al generador libre, sin datos de cartera guardados."""
from app.schemas import ChatTurn
from app.services.chat_synthesis_service import _history_for_prompt


def test_history_is_trimmed_and_drops_portfolio_answers():
    history = [
        ChatTurn(role="user", content="¿Qué es el ROIC?"),
        ChatTurn(role="assistant", content="Tu cartera guardada tiene 2 posiciones abiertas AAA 10"),
        ChatTurn(role="assistant", content="x" * 900),
    ]
    kept = _history_for_prompt(history)
    assert [t["role"] for t in kept] == ["user", "assistant"]
    assert len(kept[1]["content"]) == 400
    assert all("posiciones abiertas" not in t["content"] for t in kept)


def test_history_total_is_capped_and_empty_is_empty():
    history = [ChatTurn(role="user", content="y" * 1000) for _ in range(8)]
    assert sum(len(t["content"]) for t in _history_for_prompt(history)) <= 1600
    assert _history_for_prompt(None) == []
