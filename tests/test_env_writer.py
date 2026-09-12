from panel import env_writer


def test_form_to_env_updates_checkbox_present_and_absent():
    updates = env_writer.form_to_env_updates({"LIVE_TRADING": "on", "TARGET_TOKEN_MINT": "abc"})
    assert updates["LIVE_TRADING"] == "true"
    assert updates["I_UNDERSTAND_THE_RISK"] == "no"  # absent checkbox -> off_value
    assert updates["TARGET_TOKEN_MINT"] == "abc"


def test_merge_env_keeps_existing_secret_when_blank():
    existing = {"NEUPRINT_TOKEN": "super-secret", "MAX_TRADE_SOL": "0.05"}
    updates = {"NEUPRINT_TOKEN": "", "MAX_TRADE_SOL": "0.1"}
    merged = env_writer.merge_env(existing, updates)
    assert merged["NEUPRINT_TOKEN"] == "super-secret"
    assert merged["MAX_TRADE_SOL"] == "0.1"


def test_merge_env_overwrites_secret_when_provided():
    existing = {"NEUPRINT_TOKEN": "old"}
    updates = {"NEUPRINT_TOKEN": "new-token"}
    merged = env_writer.merge_env(existing, updates)
    assert merged["NEUPRINT_TOKEN"] == "new-token"


def test_format_env_orders_known_fields_first():
    data = {"MAX_TRADE_SOL": "0.05", "ZZZ_CUSTOM": "1", "NEUPRINT_TOKEN": "tok"}
    text = env_writer.format_env(data)
    lines = text.strip().splitlines()
    assert lines[-1] == "ZZZ_CUSTOM=1"  # unknown fields sorted to the end
    assert "NEUPRINT_TOKEN=tok" in lines
    assert "MAX_TRADE_SOL=0.05" in lines


def test_write_and_read_env_round_trip(tmp_path):
    path = tmp_path / ".env"
    env_writer.write_env(path, {"MAX_TRADE_SOL": "0.05", "TARGET_TOKEN_MINT": "abc123"})
    assert oct(path.stat().st_mode)[-3:] == "600"
    read_back = env_writer.read_env(path)
    assert read_back["MAX_TRADE_SOL"] == "0.05"
    assert read_back["TARGET_TOKEN_MINT"] == "abc123"


def test_read_env_missing_file_returns_empty_dict(tmp_path):
    assert env_writer.read_env(tmp_path / "missing.env") == {}


def test_masked_form_values_never_echoes_secrets():
    existing = {"NEUPRINT_TOKEN": "super-secret", "SOLANA_PRIVATE_KEY": "abc"}
    values = env_writer.masked_form_values(existing)
    assert values["NEUPRINT_TOKEN"] == ""
    assert values["SOLANA_PRIVATE_KEY"] == ""


def test_masked_form_values_checkbox_reflects_on_value():
    values = env_writer.masked_form_values({"LIVE_TRADING": "true"})
    assert values["LIVE_TRADING"] == "checked"
    values2 = env_writer.masked_form_values({"LIVE_TRADING": "false"})
    assert values2["LIVE_TRADING"] == ""


def test_secret_is_set():
    assert env_writer.secret_is_set({"NEUPRINT_TOKEN": "x"}, "NEUPRINT_TOKEN") is True
    assert env_writer.secret_is_set({}, "NEUPRINT_TOKEN") is False
