from memefly.discovery import CandidateRegistry, _bonding_curve_price_sol


def test_register_and_get_candidate_within_filters():
    reg = CandidateRegistry()
    reg.register_new_token("mintA", "FOO", price_sol=0.001, now=1000.0)
    for i in range(25):
        reg.record_trade("mintA", price_sol=0.0011, now=1000.0 + i)

    candidates = reg.get_candidates(now=1400.0, min_age_seconds=300, max_age_seconds=3600, min_trades=20)
    assert len(candidates) == 1
    assert candidates[0].mint == "mintA"
    assert candidates[0].trade_count == 25
    assert candidates[0].price_sol == 0.0011


def test_too_young_candidate_is_filtered_out():
    reg = CandidateRegistry()
    reg.register_new_token("mintA", "FOO", price_sol=0.001, now=1000.0)
    for _ in range(50):
        reg.record_trade("mintA", price_sol=0.001, now=1000.0)

    candidates = reg.get_candidates(now=1010.0, min_age_seconds=300, max_age_seconds=3600, min_trades=20)
    assert candidates == []


def test_too_few_trades_is_filtered_out():
    reg = CandidateRegistry()
    reg.register_new_token("mintA", "FOO", price_sol=0.001, now=1000.0)
    reg.record_trade("mintA", price_sol=0.001, now=1000.0)

    candidates = reg.get_candidates(now=1400.0, min_age_seconds=300, max_age_seconds=3600, min_trades=20)
    assert candidates == []


def test_record_trade_for_unknown_mint_is_ignored():
    reg = CandidateRegistry()
    reg.record_trade("unknown", price_sol=1.0, now=1000.0)
    assert reg.size() == 0


def test_duplicate_registration_does_not_reset_state():
    reg = CandidateRegistry()
    reg.register_new_token("mintA", "FOO", price_sol=0.001, now=1000.0)
    reg.record_trade("mintA", price_sol=0.002, now=1005.0)
    reg.register_new_token("mintA", "FOO", price_sol=0.999, now=2000.0)  # should be a no-op

    candidates = reg.get_candidates(now=1005.0, min_age_seconds=0, max_age_seconds=99999, min_trades=1)
    assert candidates[0].created_at == 1000.0
    assert candidates[0].price_sol == 0.002


def test_prune_removes_expired_candidates():
    reg = CandidateRegistry()
    reg.register_new_token("old", "OLD", price_sol=0.001, now=0.0)
    reg.register_new_token("fresh", "NEW", price_sol=0.001, now=900.0)

    reg.prune(now=1000.0, max_age_seconds=500, max_candidates=100)

    assert reg.size() == 1
    remaining = reg.get_candidates(now=1000.0, min_age_seconds=0, max_age_seconds=99999, min_trades=0)
    assert remaining[0].mint == "fresh"


def test_prune_evicts_least_active_when_over_capacity():
    reg = CandidateRegistry()
    reg.register_new_token("quiet", "QUIET", price_sol=0.001, now=1000.0)
    reg.register_new_token("busy", "BUSY", price_sol=0.001, now=1000.0)
    for _ in range(10):
        reg.record_trade("busy", price_sol=0.001, now=1001.0)

    reg.prune(now=1002.0, max_age_seconds=99999, max_candidates=1)

    assert reg.size() == 1
    remaining = reg.get_candidates(now=1002.0, min_age_seconds=0, max_age_seconds=99999, min_trades=0)
    assert remaining[0].mint == "busy"


def test_prune_does_not_evict_protected_mint_by_age():
    reg = CandidateRegistry()
    reg.register_new_token("held", "HELD", price_sol=0.001, now=0.0)
    reg.prune(now=10_000.0, max_age_seconds=500, max_candidates=100, protect=frozenset({"held"}))
    assert reg.size() == 1


def test_prune_does_not_evict_protected_mint_by_capacity():
    reg = CandidateRegistry()
    reg.register_new_token("held", "HELD", price_sol=0.001, now=1000.0)
    reg.register_new_token("busy", "BUSY", price_sol=0.001, now=1000.0)
    for _ in range(10):
        reg.record_trade("busy", price_sol=0.001, now=1001.0)

    reg.prune(now=1002.0, max_age_seconds=99999, max_candidates=1, protect=frozenset({"held"}))

    remaining = {c.mint for c in reg.get_candidates(now=1002.0, min_age_seconds=0, max_age_seconds=99999, min_trades=0)}
    assert remaining == {"held"}


def test_get_returns_none_for_unknown_mint():
    reg = CandidateRegistry()
    assert reg.get("nope") is None


def test_get_returns_candidate_ignoring_entry_filters():
    reg = CandidateRegistry()
    reg.register_new_token("old", "OLD", price_sol=0.001, now=0.0)
    candidate = reg.get("old")
    assert candidate is not None
    assert candidate.mint == "old"


def test_bonding_curve_price_computation():
    assert _bonding_curve_price_sol({"vSolInBondingCurve": 10.0, "vTokensInBondingCurve": 1000.0}) == 0.01


def test_bonding_curve_price_missing_fields_returns_none():
    assert _bonding_curve_price_sol({}) is None
    assert _bonding_curve_price_sol({"vSolInBondingCurve": 10.0, "vTokensInBondingCurve": 0}) is None
