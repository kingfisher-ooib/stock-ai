import pytest
from pydantic import ValidationError

from stock_ai.ai.ensemble import combine
from stock_ai.ai.forecast import Forecast
from stock_ai.ai.mlx_client import MLXTradeClient, TradeDecision, safe_hold
from stock_ai.ai.pipeline import ResearchPipeline
from stock_ai.config import Settings, require_local_url
from stock_ai.features.technical import compute_features
from stock_ai.risk.engine import RiskEngine


def test_decision_schema_rejects_untrusted_shapes():
    with pytest.raises(ValidationError):
        TradeDecision.model_validate({"action": "BUY", "confidence": 1.1, "reason": []})
    with pytest.raises(ValidationError):
        TradeDecision.model_validate({"action": "buy", "confidence": 0.9, "reason": []})
    assert safe_hold("invalid").action == "HOLD"


def test_malformed_llm_response_fails_closed():
    class FakeCompletions:
        def create(self, **kwargs):
            return type("Response", (), {"choices": [type("Choice", (), {
                "message": type("Message", (), {"content": '{"action":"BUY","confidence":1.2,"reason":[]}'})()
            })()]})()

    client = MLXTradeClient()
    client._client = type("FakeClient", (), {"chat": type("Chat", (), {
        "completions": FakeCompletions()
    })()})()
    result = client.make_trade_decision({"symbol": "TEST"}, {})
    assert result.action == "HOLD" and result.confidence == 0


def test_api_endpoint_and_risk_settings_reject_unsafe_values():
    with pytest.raises(ValueError):
        require_local_url("http://0.0.0.0:8080/v1")
    with pytest.raises(ValueError):
        Settings(max_position_ratio=1.5)


def test_risk_gate_overrides_confident_buy():
    engine = RiskEngine()
    signal = TradeDecision(action="BUY", confidence=0.99, reason=["test"])
    assert not engine.assess(signal, symbol="TEST", equity=100000, daily_pnl=0,
                             price=400, stop_price=None).approved
    assert not engine.assess(signal, symbol="TEST", equity=100000, daily_pnl=-2000,
                             price=400, stop_price=395).approved
    approved = engine.assess(signal, symbol="TEST", equity=100000, daily_pnl=0,
                             price=400, stop_price=395)
    assert approved.approved and approved.candidate.quantity == 10
    assert approved.candidate.stop_price == 395


def test_exit_candidate_remains_available_after_daily_loss_limit():
    engine = RiskEngine()
    signal = TradeDecision(action="SELL", confidence=0.9, reason=["test"])
    result = engine.assess(signal, symbol="TEST", equity=100000, daily_pnl=-3000,
                           price=400, stop_price=None, current_quantity=10)
    assert result.approved and result.candidate.quantity == 10


def test_round_trip_fee_counts_toward_fixed_trade_loss_budget():
    engine = RiskEngine()
    signal = TradeDecision(action="BUY", confidence=0.99, reason=["test"])
    too_expensive = engine.assess(signal, symbol="TEST", equity=100000,
                                   daily_pnl=0, price=100, stop_price=98,
                                   estimated_round_trip_fee_yen=110)
    assert not too_expensive.approved
    affordable = engine.assess(signal, symbol="TEST", equity=100000,
                                daily_pnl=0, price=100, stop_price=98,
                                estimated_round_trip_fee_yen=20)
    assert affordable.approved and affordable.candidate.quantity == 40


def test_features_exclude_later_bars():
    close = [100 + i * 0.3 for i in range(70)]
    high, low, volume = [x + 1 for x in close], [x - 1 for x in close], [1000] * 70
    before = compute_features(high, low, close, volume, as_of_index=59)
    close[60:] = [10000] * 10
    high[60:] = [10001] * 10
    low[60:] = [9999] * 10
    volume[60:] = [100000] * 10
    assert compute_features(high, low, close, volume, as_of_index=59) == before


def test_ensemble_disagreement_is_neutral():
    up = Forecast("timesfm", 1, (101.0,), "cpu")
    down = Forecast("chronos", 1, (99.0,), "cpu")
    assert combine(up, down, 100.0).signal == "neutral"


def test_pipeline_uses_only_as_of_history_and_risk_gate():
    captured = []

    class FakeForecast:
        def __init__(self, model):
            self.model = model

        def predict(self, values, horizon=5):
            captured.append(tuple(values))
            return Forecast(self.model, horizon, tuple([values[-1] + 1] * horizon), "cpu")

    class FakeLLM:
        def make_trade_decision(self, market_data, predictions):
            captured.append(market_data)
            return TradeDecision(action="BUY", confidence=0.99, reason=["test"])

    close = [100 + i * 0.3 for i in range(60)] + [100000]
    result = ResearchPipeline(FakeForecast("timesfm"), FakeForecast("chronos"), FakeLLM()).run(
        symbol="TEST", high=[x + 1 for x in close], low=[x - 1 for x in close],
        close=close, volume=[1000] * len(close), as_of_index=59,
        horizon=5, equity=100000, daily_pnl=0,
    )
    assert len(captured[0]) == len(captured[1]) == 60
    assert captured[0][-1] == close[59]
    assert captured[2]["close"] == close[59]
    assert result.decision.action == "BUY" and not result.risk.approved
