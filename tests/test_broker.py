import pytest

from bench.broker import settle_estimator
from bench.config import Settings
from bench.store import Store
from tests.helpers import candles

S = Settings()  # $10,000, cost 0.001, threshold 0.001


def pred(asof, exp):
    return {"asof": asof, "expected_return": exp, "confidence": None, "path": None}


def save(store, name, run_date, preds):
    store.save_prediction(name, run_date, {"predictions": preds})


def two_day_prices():
    return {
        "AAA": candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102)]),
    }


def test_single_winning_trade(tmp_path):
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    assert settle_estimator(st, "e", two_day_prices(), S) == 1
    eq = st.load_equity("e").iloc[0]
    assert eq["date"] == "2026-01-05"
    assert eq["day_return"] == pytest.approx(0.019)  # 102/100 - 1 - 0.001
    assert eq["equity"] == pytest.approx(10190.0)
    led = st.load_ledger("e").iloc[0]
    assert (led["entry"], led["exit"], led["traded"]) == (100, 102, 1)
    assert led["actual_cc"] == pytest.approx(0.02)  # 102 / prev close 100 - 1
    assert led["hit"] == 1


def test_cash_asset_dilutes_the_split(tmp_path):
    prices = two_day_prices()
    prices["BBB"] = candles([("2026-01-02", 50, 51, 49, 50), ("2026-01-05", 50, 51, 48, 49)])
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})  # no prediction for BBB
    settle_estimator(st, "e", prices, S)
    eq = st.load_equity("e").iloc[0]
    assert eq["n_universe"] == 2 and eq["n_traded"] == 1
    assert eq["day_return"] == pytest.approx(0.0095)
    assert eq["equity"] == pytest.approx(10095.0)


def test_asset_without_a_session_is_not_in_the_split(tmp_path):
    prices = two_day_prices()
    prices["BBB"] = candles([("2026-01-02", 50, 51, 49, 50)])  # holiday: no candle on 01-05
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    settle_estimator(st, "e", prices, S)
    eq = st.load_equity("e").iloc[0]
    assert eq["n_universe"] == 1
    assert eq["equity"] == pytest.approx(10190.0)


def test_below_threshold_stays_in_cash_but_is_still_scored(tmp_path):
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.0005)})
    settle_estimator(st, "e", two_day_prices(), S)
    eq = st.load_equity("e").iloc[0]
    assert eq["equity"] == pytest.approx(10000.0) and eq["n_traded"] == 0
    led = st.load_ledger("e").iloc[0]
    assert led["traded"] == 0 and led["net_ret"] == 0 and led["hit"] == 1


def test_wrong_direction_is_a_miss_and_a_loss_compounds(tmp_path):
    prices = {
        "AAA": candles([
            ("2026-01-02", 99, 101, 98, 100),
            ("2026-01-05", 100, 103, 99, 102),
            ("2026-01-06", 100, 101, 98, 99),
        ])
    }
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    save(st, "e", "2026-01-06", {"AAA": pred("2026-01-05", 0.01)})
    assert settle_estimator(st, "e", prices, S) == 2
    eq = st.load_equity("e")
    # day 2: open 100 close 99 -> -0.01 - 0.001 = -0.011 ; 10190 * 0.989
    assert eq["equity"].iloc[1] == pytest.approx(10077.91)
    assert st.load_ledger("e")["hit"].tolist() == [1, 0]


def test_settling_twice_changes_nothing(tmp_path):
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    settle_estimator(st, "e", two_day_prices(), S)
    assert settle_estimator(st, "e", two_day_prices(), S) == 0
    assert len(st.load_equity("e")) == 1 and len(st.load_ledger("e")) == 1


def test_no_predictions_no_rows(tmp_path):
    st = Store(tmp_path)
    assert settle_estimator(st, "e", two_day_prices(), S) == 0
    assert st.load_equity("e").empty


def test_prediction_without_a_completed_target_candle_waits(tmp_path):
    prices = {"AAA": candles([("2026-01-02", 99, 101, 98, 100)])}
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    assert settle_estimator(st, "e", prices, S) == 0
