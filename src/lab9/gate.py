"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    man, base_man = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. Metric values must be real numbers (NaN < min is False, so NaN slips past a naive gate).
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf hides a failure)")
        elif v is not None and not isinstance(v, (int, float)):
            problems.append(f"metric {k} has non-numeric value {v!r}")
    gone = sorted(k for k in (base.get("metrics") or {}) if k not in (pr.get("metrics") or {}))
    gone += sorted(m["id"] for m in spec.get("metrics", [])
                   if m["id"] in (base.get("metrics") or {}) and (pr.get("metrics") or {}).get(m["id"], 0) is None
                   and base["metrics"][m["id"]] is not None)
    if gone:
        problems.append(f"metric(s) present in the baseline are missing/None in the PR: {', '.join(gone)}")

    # 2. Evaluator health: a crashed grader must never look like a missing data point.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s) in the PR run")
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    graded = [m for m in graded if any(m in r for r in base_rows)] or graded
    bad_rows = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded
                if not isinstance(r.get(m), bool)]
    if bad_rows:
        problems.append(f"{len(bad_rows)} row value(s) are not True/False for a graded metric "
                        f"(crashed grader?), first: {bad_rows[0]}")

    # 3. Coverage: every (item, seed) exactly once, the same set as the baseline.
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    seeds = man.get("seeds") or []
    if man.get("items") is None or len(rows) != man.get("items", 0) * len(seeds):
        problems.append(f"{len(rows)} rows != {man.get('items')} items x {len(seeds)} seeds (dropped/duplicated rows)")
    dupes = len(keys) - len(set(keys))
    if dupes:
        problems.append(f"{dupes} duplicated (item, seed) row(s)")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        miss, extra = len(base_keys - set(keys)), len(set(keys) - base_keys)
        problems.append(f"(item, seed) set differs from the baseline: {miss} missing, {extra} extra (cherry-picked?)")
    if base_man and (man.get("items") != base_man.get("items") or list(seeds) != list(base_man.get("seeds") or [])):
        problems.append(f"manifest items/seeds {man.get('items')}/{seeds} != baseline "
                        f"{base_man.get('items')}/{base_man.get('seeds')}")
    if spec.get("seeds") and list(seeds) != list(spec["seeds"]):
        problems.append(f"manifest seeds {seeds} != spec seeds {spec['seeds']}")

    # 4. Slice tags come from labels, never from the run: they must match the baseline per item.
    def tags(rs: list[dict]) -> dict[str, set]:
        out: dict[str, set] = {}
        for r in rs:
            out.setdefault(r.get("item_id"), set()).update(r.get("slices") or [])
        return out
    pt, bt = tags(rows), tags(base_rows)
    moved = sorted(i for i in set(pt) & set(bt) if pt[i] != bt[i])
    if moved:
        problems.append(f"slice tags differ from the baseline for {len(moved)} item(s), e.g. {moved[0]}: "
                        f"{sorted(pt[moved[0]])} vs {sorted(bt[moved[0]])}")
    per_row = {}
    for r in rows:
        per_row.setdefault(r.get("item_id"), []).append(frozenset(r.get("slices") or []))
    if any(len(set(v)) > 1 for v in per_row.values()):
        problems.append("slice tags differ between seeds of the same item")

    # 5. The headline numbers must be what the rows say (hand-edited metrics, or metrics left
    #    over from before rows were removed).
    if rows and not bad_rows:
        problems += _recompute_mismatch(pr, spec, graded)

    # 6. Ratchet: on the same eval-set version a spec may only get stricter.
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _recompute_mismatch(pr: dict, spec: dict, graded: list[str]) -> list[str]:
    rows = pr["rows"]
    has_cost = all(isinstance(r.get("cost"), (int, float)) for r in rows)
    calc_rows = rows if has_cost else [{**r, "cost": 0.0} for r in rows]
    try:
        want = aggregate(calc_rows, graded, k_values=spec.get("pass_k", []))
    except Exception as exc:  # noqa: BLE001 -- a report we cannot recompute is not trustworthy
        return [f"metrics cannot be recomputed from rows: {exc!r}"]
    if not has_cost:
        want.pop("cost_per_success", None)
    out = []
    for k, w in want.items():
        if k not in (pr.get("metrics") or {}):
            continue
        got = pr["metrics"][k]
        if w is None and got is None:
            continue
        if w is None or got is None or not isinstance(got, (int, float)) or abs(float(got) - float(w)) > 1e-3:
            out.append(f"metric {k}={got} but rows give {w} (report edited after the run?)")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Looser-than-main checks for the same eval-set version."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                                     # a new eval-set version starts a new ratchet
    out = []
    for key in ("eval_set", "labels", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            out.append(f"RATCHET {key} changed ({base_spec.get(key)} -> {spec.get(key)}) on the same eval-set version")
    if list(spec.get("seeds") or []) != list(base_spec.get("seeds") or []):
        out.append(f"RATCHET seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    missing_k = set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or [])
    if missing_k:
        out.append(f"RATCHET pass_k dropped {sorted(missing_k)}")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if sb.get("confidence", 0.95) > bb.get("confidence", 0.95):
        out.append("RATCHET bootstrap confidence raised (wider CI hides drops)")
    if sb.get("n_resamples", 1000) < bb.get("n_resamples", 1000):
        out.append("RATCHET bootstrap n_resamples lowered")
    for k in ("rng", "method"):
        if k in bb and sb.get(k) != bb.get(k):
            out.append(f"RATCHET bootstrap {k} changed (re-rolling the CI)")

    def rules(where: str, old: dict, new: dict | None) -> list[str]:
        if new is None:
            return [f"RATCHET {where} removed"]
        r = []
        if old.get("blocking") and not new.get("blocking"):
            r.append(f"RATCHET {where} no longer blocking")
        ot, nt = old.get("threshold", old), new.get("threshold", new)
        for k in ("max", "max_increase"):
            if k in ot and (k not in nt or nt[k] > ot[k]):
                r.append(f"RATCHET {where} {k} loosened {ot[k]} -> {nt.get(k)}")
        if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
            r.append(f"RATCHET {where} min loosened {ot['min']} -> {nt.get('min')}")
        if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
            r.append(f"RATCHET {where} dropped no_significant_drop")
        return r

    new_metrics = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        out += rules(f"metric {m['id']}", m, new_metrics.get(m["id"]))
    new_slices = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        out += rules(f"slice {s['name']}/{s['metric']}", s, new_slices.get((s["name"], s["metric"])))
    return out


def _slice_values(rep: dict, metric: str, slice_name: str) -> dict[str, float]:
    """Per-item values for a slice. `pass_hat_<k>` is per-item reliability: the unbiased pass^k
    of that item's pass_rate over its seeds (an item that fails 1 seed in 5 scores 0 at k=5).
    A slice mean can hide a 1-in-5 failure; slice pass^k cannot."""
    if metric.startswith("pass_hat_") and metric[len("pass_hat_"):].isdigit():
        k = int(metric[len("pass_hat_"):])
        runs: dict[str, list[bool]] = {}
        for r in rep["rows"]:
            if slice_name in (r.get("slices") or []) and r.get("pass_rate") is not None:
                runs.setdefault(r["item_id"], []).append(bool(r["pass_rate"]))
        return {i: stats.pass_hat_k(len(v), sum(v), k) for i, v in runs.items() if len(v) >= k}
    return per_item(rep, metric, slice_name=slice_name)


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = _slice_values(pr, metric, name), _slice_values(base, metric, name)
        verdict, note = "ok", ""
        val = round(sum(a.values()) / len(a), 4) if a else None
        if val is None:
            verdict = "missing"            # an empty slice cannot vouch for anything: fail closed
        elif "min" in sl and val < sl["min"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and a:
            keys = sorted(set(a) & set(b))
            if keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000),
                                                   rng=bs.get("rng", 2027), confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
            else:
                verdict, note = "missing", "no shared items with the baseline"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}  ({len(a)} items)")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
