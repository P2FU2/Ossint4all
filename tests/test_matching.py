from monitor_jus.canonical_oab import canonicalize_oab
from monitor_jus.matching import MatchStatus, MonitoredCriterion, classify_match


CRITERIA = [
    MonitoredCriterion(criterion_type="OAB", value="SP:138094"),
    MonitoredCriterion(criterion_type="OAB", value="RJ:2556"),
    MonitoredCriterion(criterion_type="OAB", value="DF:74043"),
    MonitoredCriterion(
        criterion_type="NOME",
        value="Fernando Crespo Queiroz Neves",
        requires_secondary_evidence=True,
    ),
]


def test_confirmed_oab_sp():
    ev = classify_match(
        process_number=None,
        court="TJSP",
        text="OAB/SP 138.094",
        lawyer_names=[],
        oabs=[canonicalize_oab("SP-138094")],
        criteria=CRITERIA,
    )
    assert ev.status == MatchStatus.CONFIRMED_OAB


def test_rj_2556a_does_not_confirm_2556():
    ev = classify_match(
        process_number=None,
        court="TJRJ",
        text="OAB/RJ 2556A",
        lawyer_names=[],
        oabs=[canonicalize_oab("RJ-2556A")],
        criteria=CRITERIA,
    )
    assert ev.status != MatchStatus.CONFIRMED_OAB


def test_rj_2556_confirms():
    ev = classify_match(
        process_number=None,
        court="TJRJ",
        text="OAB/RJ 2556",
        lawyer_names=[],
        oabs=[canonicalize_oab("RJ-2556")],
        criteria=CRITERIA,
    )
    assert ev.status == MatchStatus.CONFIRMED_OAB


def test_name_fragment_ambiguous():
    ev = classify_match(
        process_number=None,
        court=None,
        text="Fernando Neves",
        lawyer_names=["Fernando Neves"],
        oabs=[],
        criteria=CRITERIA,
    )
    assert ev.status == MatchStatus.AMBIGUOUS


def test_full_name_plus_court_probable():
    ev = classify_match(
        process_number=None,
        court="STF",
        text="Fernando Crespo Queiroz Neves",
        lawyer_names=["Fernando Crespo Queiroz Neves"],
        oabs=[],
        criteria=CRITERIA,
    )
    assert ev.status == MatchStatus.PROBABLE_NAME


def test_name_plus_known_process_confirmed():
    crits = CRITERIA + [
        MonitoredCriterion(criterion_type="PROCESSO", value="00000010020203000000")
    ]
    ev = classify_match(
        process_number="0000001-00.2020.3.00.0000",
        court="STJ",
        text="qualquer",
        lawyer_names=["Fernando Crespo Queiroz Neves"],
        oabs=[],
        criteria=crits,
    )
    assert ev.status == MatchStatus.CONFIRMED_PROCESS
