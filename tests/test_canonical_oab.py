import pytest

from monitor_jus.canonical_oab import CanonicalOab, OabCanonicalizeError, canonicalize_oab


def test_canonicalize_oab_sp_formatted():
    oab = canonicalize_oab("OAB/SP 123.456")
    assert oab.state == "SP"
    assert oab.number == "123456"
    assert oab.suffix is None
    assert oab.canonical == "SP-123456"


def test_canonicalize_oab_compact():
    oab = canonicalize_oab("138094SP")
    assert oab.canonical == "SP-138094"


def test_canonicalize_with_default_state():
    oab = canonicalize_oab("2556A", default_state="RJ")
    assert oab.canonical == "RJ-2556A"
    assert oab.suffix == "A"


def test_canonicalize_without_state_no_invent():
    oab = canonicalize_oab("2556A")
    assert oab.state is None
    assert oab.canonical is None


def test_suffix_mismatch_does_not_match():
    crit = canonicalize_oab("RJ-2556")
    hit = canonicalize_oab("RJ-2556A")
    assert not hit.matches_criterion(crit)


def test_exact_suffix_match():
    crit = canonicalize_oab("SP:138094")
    hit = canonicalize_oab("OAB/SP 138.094")
    assert hit.matches_criterion(crit)


def test_conflicting_uf_invalid():
    with pytest.raises(OabCanonicalizeError):
        canonicalize_oab("SP 138094 RJ")
