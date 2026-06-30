from pathlib import Path

import pytest

from app.freqtrade_compat import build_show_config_payload, translate_freqtrade_to_system


def compat_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "freqtrade_compat.json"


def test_freqtrade_compat_translates_default_config_to_paper_mode() -> None:
    config, raw, _base_dir = translate_freqtrade_to_system(compat_config_path())

    assert raw["strategy"] == "EMATrendStrategy"
    assert config.app.mode.value == "paper"
    assert config.strategy.active_strategy == "ema_trend"
    assert config.exchange.symbols == ["BTC/USDT", "ETH/USDT"]
    assert config.exchange.timeframes == ["1m"]
    assert config.execution.paper_initial_cash == 10000.0
    assert config.app.dashboard.web_enabled


def test_freqtrade_compat_can_force_testnet_mode() -> None:
    config, _raw, _base_dir = translate_freqtrade_to_system(
        compat_config_path(),
        dry_run=False,
        sandbox=True,
        dashboard_choice="none",
    )
    assert config.app.mode.value == "testnet"
    assert not config.app.dashboard.enabled


def test_freqtrade_compat_can_force_monitor_mode() -> None:
    config, _raw, _base_dir = translate_freqtrade_to_system(
        compat_config_path(),
        monitor=True,
        dashboard_choice="web",
    )
    assert config.app.mode.value == "monitor"
    assert config.app.dashboard.web_enabled


def test_freqtrade_compat_blocks_unsafe_live_mode() -> None:
    with pytest.raises(SystemExit, match="默认仍禁止直接实盘"):
        translate_freqtrade_to_system(
            compat_config_path(),
            dry_run=False,
            sandbox=False,
            monitor=False,
        )


def test_show_config_payload_contains_public_strategy_name() -> None:
    config, raw, _base_dir = translate_freqtrade_to_system(compat_config_path())
    payload = build_show_config_payload(config, raw, compat_config_path())
    assert payload["resolved_strategy"]["public"] == "EMATrendStrategy"
    assert payload["translated_system_config"]["app"]["mode"] == "paper"
