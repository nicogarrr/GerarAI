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


def test_ranking_and_ticker_position_answers_do_not_reach_the_general_llm():
    history = [
        ChatTurn(role="assistant", content="La posición con el coste medio más alto es ASTS: 61,20 USD."),
        ChatTurn(role="assistant", content="Tu posición guardada en ASTS: 318 acciones, coste medio 55,10 USD, valor 16.000 EUR."),
        ChatTurn(role="assistant", content="Patrimonio neto: 6.630,17 EUR (datos guardados en la app)."),
        ChatTurn(role="user", content="¿Qué es el margen de seguridad?"),
    ]
    kept = _history_for_prompt(history)
    assert [t["role"] for t in kept] == ["user"]
    joined = " ".join(t["content"] for t in kept)
    assert "ASTS" not in joined and "61,20" not in joined and "6.630" not in joined
