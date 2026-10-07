"""Causality, leakage boundaries, input checks, and durable research records."""
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from research.alpha_lab.__main__ import run
from research.alpha_lab.evaluation import evaluate, portfolio, weights
from research.alpha_lab.expressions import Proposal, compute, fingerprint, parse
from research.alpha_lab.ledger import Ledger
from research.alpha_lab.panel import synthetic, validate


@pytest.mark.parametrize("expression", ["__import__('os').system('id')", "close.shift(-1)", "delay(close, -1)", "delay(close, True)", "rank(close, other=1)", "close + volume", "open"])
def test_untrusted_expression_rejected(expression):
    with pytest.raises(ValueError):
        parse(expression)


def test_expression_fingerprint_ignores_whitespace():
    assert fingerprint("rank(close)") == fingerprint("rank( close )")


def test_future_price_change_does_not_change_earlier_signal():
    panel = synthetic(days=90, assets=5)
    before = validate(panel)
    edited = panel.copy()
    boundary = sorted(panel.date.unique())[60]
    edited.loc[edited.date >= boundary, "close"] *= 3
    after = validate(edited)
    expression = "neg(rank(div(close, ts_mean(close, 10))))"
    pd.testing.assert_frame_equal(compute(expression, before).iloc[:60], compute(expression, after).iloc[:60])


def test_weight_neutrality_gross_and_missing_signal():
    signal = pd.DataFrame([[1, 2, 3, 4], [np.nan, 1, 2, 3], [np.nan, np.nan, 1, 2]])
    result = weights(signal)
    assert np.allclose(result.sum(axis=1), 0)
    assert np.allclose(result.abs().sum(axis=1), [1, 1, 0])
    assert result.iloc[1, 0] == 0


def test_execution_has_a_full_bar_after_observation():
    dates = pd.date_range("2024-01-01", periods=5)
    close = pd.DataFrame({"a": [100, 110, 121, 121, 121], "b": [100] * 5, "c": [100] * 5}, index=dates)
    signal = pd.DataFrame([[3, 2, 1]] + [[1, 2, 3]] * 4, columns=close.columns, index=dates)
    result = portfolio(signal, close, cost_bps=0)
    assert result.gross_return.iloc[1] == 0
    assert result.gross_return.iloc[2] == pytest.approx(.05)


def test_cost_is_charged_on_initial_trade():
    panel = validate(synthetic(days=50, assets=4))
    signal = compute("rank(close)", panel)
    free = portfolio(signal, panel["close"], 0)
    costly = portfolio(signal, panel["close"], 10)
    assert costly.turnover.iloc[2] == pytest.approx(1)
    assert np.allclose(free.net_return - costly.net_return, costly.turnover * .001)


def test_training_metrics_do_not_change_with_holdout_prices():
    fields = validate(synthetic(days=100, assets=6))
    signal = compute("rank(div(close, delay(close, 5)))", fields)
    original, _ = evaluate(signal, fields["close"])
    changed = {k: v.copy() for k, v in fields.items()}
    changed["close"].iloc[60:] *= np.linspace(1, 2, 40)[:, None]
    new_signal = compute("rank(div(close, delay(close, 5)))", changed)
    revised, _ = evaluate(new_signal, changed["close"])
    assert original["train"] == revised["train"]


@pytest.mark.parametrize("kind", ["duplicate", "missing", "negative", "infinite"])
def test_panel_quality_failures(kind):
    panel = synthetic(days=50, assets=4)
    if kind == "duplicate":
        panel = pd.concat([panel, panel.iloc[:1]])
    elif kind == "missing":
        panel = panel.iloc[1:]
    elif kind == "negative":
        panel.loc[0, "close"] = -1
    else:
        panel.loc[0, "volume"] = np.inf
    with pytest.raises(ValueError):
        validate(panel)


def test_ledger_deduplication_and_configuration_identity(tmp_path):
    ledger = Ledger(tmp_path / "runs.sqlite")
    proposal = {"name": "x", "hypothesis": "baseline", "expression": "rank(close)"}
    one = ledger.record(proposal, {"cost": 5}, "completed", {"metric": 1})
    renamed = {**proposal, "name": "renamed", "expression": "rank( close )"}
    duplicate = ledger.record(renamed, {"cost": 5}, "completed", {"metric": 9})
    changed = ledger.record(proposal, {"cost": 10}, "completed", {"metric": 1})
    assert duplicate["id"] == one["id"] and duplicate["duplicate"]
    assert changed["id"] != one["id"]
    with sqlite3.connect(ledger.path) as db:
        assert json.loads(db.execute("SELECT metrics_json FROM experiments WHERE id=?", (one["id"],)).fetchone()[0])["metric"] == 1


def test_failed_and_duplicate_candidates_are_visible(tmp_path):
    panel = tmp_path / "panel.csv"
    synthetic(days=60, assets=4).to_csv(panel, index=False)
    proposals = tmp_path / "ideas.json"
    proposals.write_text(json.dumps([
        {"name": "good", "hypothesis": "baseline", "expression": "rank(close)"},
        {"name": "same", "hypothesis": "same syntax", "expression": "rank( close )"},
        {"name": "bad", "hypothesis": "invalid", "expression": "delay(close, -1)"}]))
    result = run(panel, proposals, tmp_path / "out")
    assert [r["status"] for r in result] == ["completed", "duplicate_expression", "failed"]
    with sqlite3.connect(tmp_path / "out/experiments.sqlite") as db:
        assert db.execute("SELECT count(*) FROM experiments WHERE status='failed'").fetchone()[0] == 1


def test_extra_proposal_fields_are_rejected():
    with pytest.raises(ValueError):
        Proposal.from_dict({"name": "x", "hypothesis": "x", "expression": "close", "execute_python": "x"})


def test_holdout_only_signal_cannot_qualify_a_candidate(tmp_path):
    panel = tmp_path / "panel.csv"
    synthetic(days=100, assets=4).to_csv(panel, index=False)
    proposals = tmp_path / "ideas.json"
    proposals.write_text(json.dumps([{"name": "late", "hypothesis": "long lookback",
                                      "expression": "rank(delay(close, 80))"}]))
    # The factor has 20 valid holdout dates but none in the 60-date
    # development interval. Holdout availability must not qualify it.
    result = run(panel, proposals, tmp_path / "out")
    assert result[0]["status"] == "failed"
    assert "development period" in result[0]["error"]
