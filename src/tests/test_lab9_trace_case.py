"""Regression test from docs/trace_case.md: seeded_regression C-014@11 (FM-05 pre_deducted).

First wrong step: event 5 `proposal` 120.000 after the agent itself subtracted the prior
30.000 refund; the host subtracts it again, so the ledger holds 90.000 instead of 120.000,
while the reply still says 120.000đ (FM-08 symptom). The same claim@seed on `fixed` passes.
"""
import pytest

pytestmark = pytest.mark.student


def _ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="trace_case", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


def _pre_deducted_steps(events):
    """Step-level check: a `proposal` below the `quote` right after a `refund_history` read is
    the agent doing the host's per-order cap itself (FM-05)."""
    quote = next((e["payload"]["amount_vnd"] for e in events if e.get("kind") == "quote"), None)
    seen_history = False
    bad = []
    for i, e in enumerate(events, 1):
        if e.get("kind") == "refund_history" and e["payload"].get("refunded_vnd"):
            seen_history = True
        if e.get("kind") == "proposal" and seen_history and quote is not None and e["payload"]["amount_vnd"] < quote:
            bad.append(i)
    return bad


@pytest.fixture(scope="module")
def cases():
    from lab9.trace_case import investigate

    return {shape: investigate(shape, "C-014", 11) for shape in ("seeded_regression", "fixed")}


def test_first_wrong_step_is_event_5_proposal(cases):
    events = cases["seeded_regression"]["trial"]["events"]
    assert _pre_deducted_steps(events) == [5]
    assert events[4]["kind"] == "proposal" and events[4]["payload"]["amount_vnd"] == 120000


def test_graders_catch_the_regression(cases):
    from lab9.graders import RefundAmountCorrect, ReplyLedgerMatch

    case = cases["seeded_regression"]
    assert case["trial"]["snapshot"]["refund_vnd"] == 90000
    assert RefundAmountCorrect().evaluate(_ctx(case)).value is False
    assert ReplyLedgerMatch().evaluate(_ctx(case)).value is False


def test_fixed_shape_passes_same_claim_seed(cases):
    from lab9.graders import RefundAmountCorrect, ReplyLedgerMatch

    case = cases["fixed"]
    assert _pre_deducted_steps(case["trial"]["events"]) == []
    assert case["trial"]["lab8_pass"] is True
    assert RefundAmountCorrect().evaluate(_ctx(case)).value is True
    assert ReplyLedgerMatch().evaluate(_ctx(case)).value is True
