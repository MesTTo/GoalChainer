"""Purpose: measure how well a request's elements are read by GoalChainer's keyword extractor and by the semantic
rewriter's judge, fit the judged reading's constants on the tuning requests (tests/fixtures/judged_requests.json) and
report them on the held-out requests (tests/fixtures/judged_requests_heldout.json), which nothing was fitted to.

An element's opinion is its best-matching statement's, the one with the highest projection at the element's base rate,
discounted by the judge's trust; it counts as present when its projection passes one half, as GoalChainer's native
decision counts a belief. The base rates are the elements' shares of the tuning requests and the trust is the posterior
mean, under a uniform prior, of the likelihood semrewrite's fit_trust maximises over the tuning requests; both must
equal the constants in goal_chainer.judged_elements, which the deployed reading uses. Tuning accuracy is
leave-one-request-out, each request read at the constants fitted on the others; held-out accuracy reads each request
at the constants fitted on all tuning requests. The first statements written for the elements are reported beside the
deployed ones, and so is the privacy-protective reading that counts data sensitive when the keywords or the judge say so.

Run with the semantic rewriter's environment, which has the judge's model:
    PYTHONPATH=src:$SEMREWRITE /path/to/semrewrite/.venv/bin/python benchmarks/judged_elements.py
It writes benchmarks/judged_elements.json and prints the tables.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from semrewrite.judges import make
from semrewrite.judges.metrics import fit_trust
from semrewrite.opinion import Opinion

from goal_chainer import judged_elements as deployed
from goal_chainer.evidence import _extract_keyword_evidence

ROOT = Path(__file__).resolve().parents[1]
TUNING = ROOT / "tests" / "fixtures" / "judged_requests.json"
HELD_OUT = ROOT / "tests" / "fixtures" / "judged_requests_heldout.json"
RESULTS = ROOT / "benchmarks" / "judged_elements.json"
ELEMENTS = deployed.ELEMENTS

# am[related a-gcje-statements]
# The statements first written for the elements, before tuning, reported beside the deployed ones.
_CATEGORIES = ("customer emails", "order IDs", "request payloads", "tokens or secrets", "full traces", "raw logs")
FIRST_STATEMENTS: dict[str, tuple[str, ...]] = {
    "sensitive-data": (
        *(f"The data may include {label}." for label in _CATEGORIES),
        "The text mentions private information about people.",
    ),
    "public-data": ("The information is safe to share publicly.",),
    "unverified": ("The cause of the problem is not yet known.", "The facts are not yet confirmed."),
    "coordination-needed": ("Several teams need to work together.",),
}
STATEMENT_SETS = {"deployed": deployed.STATEMENTS, "first": FIRST_STATEMENTS}
# Simpson's rule intervals over [0, 1] for the trust's posterior mean; the integrand is smooth, a product of linear
# functions of the trust, so the rule's error is far below the three decimals the constant keeps.
_INTERVALS = 2000


# am[implements a-goalchainer-judged-elements.measure]
def keyword_elements(text: str) -> dict[str, bool]:
    """GoalChainer's keyword extractor's reading of a request, element by element."""
    ev = _extract_keyword_evidence(text)
    return {"sensitive-data": bool(ev.sensitive_categories), "public-data": ev.public_declared,
            "unverified": not ev.facts_ready, "coordination-needed": ev.coordination_needed}


# am[implements a-goalchainer-judged-elements.measure]
def best(raw: list[Opinion], statements: tuple[str, ...], trust: float, rate: float) -> tuple[Opinion, str]:
    """The statement opinion with the highest projection at the base rate, discounted by the trust, and its statement;
    the first such statement on a tie, as the deployed reading picks."""
    return max(((o.with_base_rate(rate).discount(trust), s) for o, s in zip(raw, statements)),
               key=lambda pair: pair[0].projection)


# am[implements a-gcje-trust-posterior-mean]
def posterior_mean_trust(opinions: list[Opinion], labels: list[bool]) -> float:
    """The posterior mean of the trust t under a uniform prior on [0, 1], given rows that each hold with the
    projection of their opinion discounted by t: the likelihood fit_trust maximises, integrated by Simpson's rule.
    A row's projection is linear in t, from its base rate at t = 0 to its own projection at t = 1.

    Time: (_INTERVALS + 1) x n projections, n = len(opinions)."""
    rows = [(o.discount(0.0).projection, o.discount(1.0).projection, y) for o, y in zip(opinions, labels, strict=True)]
    ts = [k / _INTERVALS for k in range(_INTERVALS + 1)]

    def loglik(t: float) -> float:
        total = 0.0
        for low, high, y in rows:
            p = low + t * (high - low)
            q = p if y else 1.0 - p
            if q <= 0.0:
                return -math.inf
            total += math.log(q)
        return total

    logs = [loglik(t) for t in ts]
    top = max(logs)
    weights = [(1 if k in (0, _INTERVALS) else 4 if k % 2 else 2) * math.exp(v - top) for k, v in enumerate(logs)]
    return sum(t * w for t, w in zip(ts, weights)) / sum(weights)


# am[implements a-goalchainer-judged-elements.measure]
class Readings:
    """Raw judge opinions of every request of a fixture against every statement of a statement set."""

    def __init__(self, requests: list[dict], statements: dict[str, tuple[str, ...]], raw: dict[tuple[str, str], Opinion]):
        self.requests, self.statements = requests, statements
        self.raw = [{e: [raw[(r["text"], s)] for s in statements[e]] for e in ELEMENTS} for r in requests]

    def rows(self, indices, rates: dict[str, float], trust: float):
        """(opinion, statement, label) of each element of each indexed request at the rates and trust."""
        return [(*best(self.raw[i][e], self.statements[e], trust, rates[e]), self.requests[i][e], e)
                for i in indices for e in ELEMENTS]

    def fit(self, indices) -> tuple[dict[str, float], float, float]:
        """The base rates, the posterior-mean trust and the maximum-likelihood trust fitted on the indexed requests.
        The best statement is chosen at full trust, as at any trust: discounting keeps the order of projections at a
        rate."""
        rates = {e: sum(self.requests[i][e] for i in indices) / len(indices) for e in ELEMENTS}
        rows = self.rows(indices, rates, 1.0)
        opinions, labels = [o for o, *_ in rows], [y for _, _, y, _ in rows]
        return rates, posterior_mean_trust(opinions, labels), fit_trust(opinions, labels)


# am[implements a-gcje-union]
# am[implements a-goalchainer-judged-elements.measure]
def summarise(rows: list[dict], key) -> dict[str, dict[str, float]]:
    """Per element: requests stating it, right, false alarms, misses and, for opinions, the Brier score."""
    out = {}
    for e in ELEMENTS:
        said = [key(row)[e] for row in rows]
        truth = [row["labels"][e] for row in rows]
        present = [s > 0.5 if isinstance(s, float) else s for s in said]
        out[e] = {"stating": sum(truth), "right": sum(p == y for p, y in zip(present, truth)),
                  "false_alarms": sum(p and not y for p, y in zip(present, truth)),
                  "misses": sum(y and not p for p, y in zip(present, truth))}
        if all(isinstance(s, float) for s in said):
            out[e]["brier"] = round(sum((s - y) ** 2 for s, y in zip(said, truth)) / len(rows), 4)
    return out


# am[implements a-goalchainer-judged-elements.measure]
def main(judge_name: str = deployed.JUDGE) -> None:
    sets = {name: json.loads(path.read_text())["requests"] for name, path in (("tuning", TUNING), ("held_out", HELD_OUT))}
    pairs = sorted({(r["text"], s) for requests in sets.values() for r in requests
                    for statements in STATEMENT_SETS.values() for e in ELEMENTS for s in statements[e]})
    judge = make(judge_name, trust=1.0, base_rate=0.5)
    try:
        raw = dict(zip(pairs, judge.sentence_opinions(pairs), strict=True))
    finally:
        judge.close()

    report: dict = {"judge": judge_name, "statement_sets": {}}
    tables = []
    for set_name, statements in STATEMENT_SETS.items():
        tuning = Readings(sets["tuning"], statements, raw)
        held_out = Readings(sets["held_out"], statements, raw)
        everyone = list(range(len(tuning.requests)))
        rates, trust, ml_trust = tuning.fit(everyone)
        if set_name == "deployed" and (abs(trust - deployed.TRUST) > 5e-4 or any(
                not math.isclose(rates[e], deployed.BASE_RATES[e]) for e in ELEMENTS)):
            sys.exit(f"goal_chainer.judged_elements constants drifted: trust {trust:.4f} against {deployed.TRUST}, "
                     f"rates {rates} against {deployed.BASE_RATES}")
        results = {}
        for split, readings in (("tuning", tuning), ("held_out", held_out)):
            rows = []
            for i, r in enumerate(readings.requests):
                if split == "tuning":
                    fold_rates, fold_trust, _ = tuning.fit([j for j in everyone if j != i])
                else:
                    fold_rates, fold_trust = rates, trust
                read = {e: (o, s) for o, s, _, e in readings.rows([i], fold_rates, fold_trust)}
                kw = keyword_elements(r["text"])
                judged = {e: round(read[e][0].projection, 6) for e in ELEMENTS}
                rows.append({"text": r["text"], "labels": {e: r[e] for e in ELEMENTS}, "keywords": kw,
                             "judged": judged, "statements": {e: read[e][1] for e in ELEMENTS},
                             "protective": {**{e: judged[e] > 0.5 for e in ELEMENTS},
                                            "sensitive-data": kw["sensitive-data"] or judged["sensitive-data"] > 0.5}})
            results[split] = {"requests": len(rows), "keywords": summarise(rows, lambda row: row["keywords"]),
                              "judged": summarise(rows, lambda row: row["judged"]),
                              "protective": summarise(rows, lambda row: row["protective"]), "rows": rows}
        report["statement_sets"][set_name] = {"statements": {e: list(statements[e]) for e in ELEMENTS},
                                              "base_rates": rates, "trust": trust, "ml_trust": ml_trust, **results}
        tables.append((set_name, trust, ml_trust, results))
    RESULTS.write_text(json.dumps(report, indent=1) + "\n")

    for set_name, trust, ml_trust, results in tables:
        print(f"\n{set_name} statements: trust {trust:.3f} (posterior mean; maximum likelihood {ml_trust:.3f})")
        for split, result in results.items():
            n = result["requests"]
            print(f"\n{split}, {n} requests: right (false alarms, misses)")
            print("| element | stating it | keywords | judge | keywords or judge |\n|---|---|---|---|---|")
            for e in ELEMENTS:
                k, j, p = (result[r][e] for r in ("keywords", "judged", "protective"))
                cell = lambda s: f"{s['right']} ({s['false_alarms']}, {s['misses']})"  # noqa: E731
                both = cell(p) if e == "sensitive-data" else "-"
                print(f"| {e} | {j['stating']} | {cell(k)} | {cell(j)}, Brier {j['brier']} | {both} |")


if __name__ == "__main__":
    main(*sys.argv[1:])
