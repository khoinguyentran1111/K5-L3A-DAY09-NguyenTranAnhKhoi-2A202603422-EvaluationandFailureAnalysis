"""Single-bug probe: evidence for the failure taxonomy (docs/failure_taxonomy.md).

    python -m lab9.fm_probe --bug stale_clause --claim C-006 --seed 11   # one trace, like trace_case
    python -m lab9.fm_probe --bug sibling_refund --scan                  # which claim@seed it breaks

Each probe is the `fixed` shape plus exactly ONE bug switch from lab9.variant_agent, so a
failing trial points at one failure mode. Shapes are registered at run time (`probe_<bug>`);
no Lab 8 file is edited and every run uses a fresh temp store.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from lab8.console import utf8_stdio
from lab8.db import load_json, load_jsonl
from lab9 import trace_case, variants
from lab9.eval import WORLD, make_task
from lab9.variant_agent import BENIGN, BUGS, make_shape

# Bug switch -> taxonomy code (docs/failure_taxonomy.md).
BUG_TO_FM = {
    "leaky_trace": "FM-01",
    "ignore_denied": "FM-02",
    "ticket_trust": "FM-03",
    "quiet_override": "FM-03",
    "sum_parts": "FM-04",
    "round_down": "FM-04",
    "pre_deducted": "FM-05",
    "stale_clause": "FM-06",
    "sibling_refund": "FM-07",
    "misreport": "FM-08",
}
SEEDS = (11, 22, 33, 44, 55)


def register(bug: str) -> str:
    if bug not in BUGS - BENIGN:
        raise SystemExit(f"unknown bug switch {bug!r}; pick one of {sorted(BUGS - BENIGN)}")
    from lab8.shapes import SHAPES
    variants.register()
    name = f"probe_{bug}"
    # ticket_trust is the only switch that must NOT carry no_override (it is the override).
    bugs = {bug} if bug in ("ticket_trust", "quiet_override") else {"no_override", bug}
    SHAPES.setdefault(name, make_shape(name, frozenset(bugs)))
    return name


def reply_text(trial: dict) -> str:
    return next((e["payload"]["text"] for e in trial["events"] if e.get("kind") == "reply"), "")


def scan(shape: str) -> list[str]:
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    out = []
    with tempfile.TemporaryDirectory(prefix="lab9-probe-", ignore_cleanup_errors=True) as tmp:
        task = make_task(shape, load_json(WORLD), claims, labels, Path(tmp))
        for c in claims:
            for s in SEEDS:
                t = task({"claim_id": c["claim_id"], "seed": s})
                lab = labels[c["claim_id"]]
                ledger = t["snapshot"].get("refund_vnd")
                said = reply_text(t)
                # FM-08 is invisible to the Lab 8 grader: flag a reply amount the ledger does not hold.
                misreport = ledger and f"{int(ledger):,}".replace(",", ".") + "đ" not in said and "hoàn" in said
                if not t["lab8_pass"] or ledger != lab["refund_vnd"] or t["unexpected_rows"] or misreport:
                    out.append(f"{c['claim_id']}@{s}  lab8={'PASS' if t['lab8_pass'] else 'FAIL'} "
                               f"({t['lab8_reason'][:32]})  status={t['result'].get('status')}  "
                               f"ledger={ledger} label={lab['refund_vnd']}  unexpected_rows={t['unexpected_rows']}"
                               f"  reply={said[:48]!r}")
    return out


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.fm_probe")
    ap.add_argument("--bug", required=True, help="one bug switch from lab9.variant_agent.BUGS")
    ap.add_argument("--claim")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--scan", action="store_true", help="run all 14 claims x 5 seeds, list broken trials")
    args = ap.parse_args(argv)
    shape = register(args.bug)
    print(f"# probe {shape} -> {BUG_TO_FM.get(args.bug, '?')}")
    if args.scan:
        rows = scan(shape)
        for r in rows:
            print(" ", r)
        print(f"{len(rows)} broken trial(s) / {14 * len(SEEDS)}")
        return 0
    if not args.claim:
        ap.error("--claim is required without --scan")
    return trace_case.main(["--shape", shape, "--claim", args.claim, "--seed", str(args.seed)])


if __name__ == "__main__":
    raise SystemExit(main())
