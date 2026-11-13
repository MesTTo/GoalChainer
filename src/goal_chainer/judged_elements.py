"""Purpose: read a request's elements, the circumstances GoalChainer's native policy decides on, as the semantic
rewriter's judge's opinions that the request entails a statement of each element, and believe them in native SNARS in
place of the policy's label word lists, so a paraphrase, a negation or a hedge reads as what it says and each element
carries how sure the judge is. GOALCHAINER_ELEMENTS=judged selects this reading in native mode; GOALCHAINER_SEMREWRITE
names the semrewrite command, else semrewrite is found on PATH."""

from __future__ import annotations

import json
import math
import os
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from .snars_models import (
    EvidenceCounts,
    SnarsBelief,
    SnarsDependencyUnavailableError,
    SnarsInvalidInputError,
    SnarsPersistenceError,
    SnarsProtocolError,
    SnarsTimeoutError,
    SubjectiveOpinion,
)

if TYPE_CHECKING:
    from .snars_reasoner import SnarsSession

READING_VARIABLE = "GOALCHAINER_ELEMENTS"
COMMAND_VARIABLE = "GOALCHAINER_SEMREWRITE"
# keywords: the native policy believes an element when a parsed label is on its word list (gc assert-request-context!).
# judged: this module believes each element at the judge's opinion, and the policy asserts none.
READINGS = ("keywords", "judged")

ELEMENTS = ("sensitive-data", "public-data", "unverified", "coordination-needed")

# am[implements a-gcje-statements]
# GoalChainer's own words written as sentences: evidence.py's sensitive categories and signal phrases and the native
# policy's label lists, beside the first statements written for them. A request states an element when it entails one
# of its statements. Kept by one rule on the 26 requests of tests/fixtures/judged_requests.json only: a statement
# stays when, at full trust and the element's base rate, it passes one half on some request stating the element and on
# none lacking it (c-gcje-selection-rule). On the 42 held-out requests of tests/fixtures/judged_requests_heldout.json
# they read 153 of 168 elements right, the keyword extractor 142 and the first statements 140
# (benchmarks/judged_elements.json, c-gcje-heldout-results); coordination stays below the keywords there, 36 to 41,
# with 5 false alarms (c-gcje-coordination-false-alarms).
STATEMENTS: dict[str, tuple[str, ...]] = {
    "sensitive-data": (
        "The data may include customer emails.",
        "The data may include order IDs.",
        "The data may include request payloads.",
        "The data may include raw logs.",
        "The data includes customer emails.",
        "The data includes order IDs.",
        "The data includes request payloads.",
        "The data includes tokens or secrets.",
        "The data includes raw logs.",
        "The data includes customer information.",
        "The data includes personally identifiable information.",
        "The data includes credentials.",
        "The data includes secrets.",
        "The data includes identifiers.",
        "The data includes API keys.",
        "The data includes customer data.",
        "The data includes sensitive data.",
    ),
    "public-data": (
        "The information is safe to share publicly.",
        "There is no sensitive data.",
        "There is no personal data.",
        "There is no customer data.",
        "Nothing sensitive is included.",
        "There is no PII.",
        "The data is not sensitive.",
        "It is safe to publish.",
        "It is public information.",
        "It is non-sensitive.",
    ),
    "unverified": (
        "The cause of the problem is not yet known.",
        "The facts are not yet confirmed.",
        "The facts are unverified.",
        "The facts are not ready.",
        "They are still investigating.",
        "They do not know yet.",
        "The root cause is unknown.",
        "There is no root cause yet.",
    ),
    "coordination-needed": (
        "Engineering and support need to coordinate.",
        "Responders need to coordinate.",
        "The team needs an incident channel.",
        "The on-call engineers need to coordinate.",
        "Engineering and support need to work together.",
        "Responders need to share information with each other.",
        "People need to coordinate.",
    ),
}

JUDGE = "nli-deberta-large"
SOURCE = f"semrewrite:{JUDGE}"
# am[implements a-gcje-trust-posterior-mean]
# The judge's trust: the posterior mean, under a uniform prior on [0, 1], of the likelihood semrewrite's fit_trust
# maximises over the 26 tuning requests' four elements. The maximum itself sits at 1, since no statement fires on a
# tuning request lacking its element, and would let the judge's softmax enter SNARS nearly dogmatic
# (c-gcje-ml-trust-boundary, i-gcje-dogmatic-evidence). benchmarks/judged_elements.py recomputes it and the base
# rates, and refuses to report when either drifts from these constants.
TRUST = 0.946
# Each element's base rate: its share of the 26 tuning requests, the prior a request states it.
BASE_RATES: dict[str, float] = {
    "sensitive-data": 11 / 26,
    "public-data": 5 / 26,
    "unverified": 5 / 26,
    "coordination-needed": 5 / 26,
}

# semrewrite judge writes each number rounded to six decimals, so a row's belief, disbelief and uncertainty may miss
# summing to one by three half-units of the sixth decimal.
_ROUNDING = 3 * 0.5e-6
# The base rate the judge is asked to report at. Each element's own replaces it exactly, since discounting scales belief
# and disbelief and keeps the base rate (c-gcje-rebase-exact).
_REPORTED_BASE_RATE = 0.5
# W, the prior weight SNARS's opinion from evidence adds to r + s (mettabase lib/mettabase/snars/truth.metta, sn opinion
# and sn op-to-ev; Jøsang 2016, Eq. 3.11).
_PRIOR_WEIGHT = 2.0

JudgeRun = Callable[[Sequence[tuple[str, str]]], Sequence[Any]]


# am[implements a-gcje-runner]
def selected_reading() -> str:
    """The element reading GOALCHAINER_ELEMENTS selects: keywords when unset or empty, else keywords or judged."""

    value = os.environ.get(READING_VARIABLE, "").strip().lower() or "keywords"
    if value not in READINGS:
        raise SnarsInvalidInputError(
            "GOALCHAINER_ELEMENTS must be keywords or judged.",
            details={"variable": READING_VARIABLE, "value": value},
        )
    return value


# am[implements a-gcje-believe]
@dataclass(frozen=True)
class ElementOpinion:
    """The judge's opinion that a request states an element: its best-matching statement's, at the element's base
    rate, discounted by the judge's trust. A dogmatic opinion has no finite evidence, so it cannot be held."""

    element: str
    statement: str
    opinion: SubjectiveOpinion

    def __post_init__(self) -> None:
        if self.element not in ELEMENTS or self.statement not in STATEMENTS[self.element]:
            raise SnarsInvalidInputError(
                "An element opinion must name an element and one of its statements.",
                details={"element": self.element, "statement": self.statement},
            )
        if self.opinion.uncertainty <= 0.0:
            raise SnarsProtocolError(
                "The judge's opinion is dogmatic, so it has no finite evidence to believe.",
                details={"element": self.element, "statement": self.statement},
            )

    # am[rests-on c-gcje-evidence-roundtrip]
    @property
    def evidence(self) -> EvidenceCounts | None:
        """The evidence SNARS reads back as this opinion, W b/u for and W d/u against at its base rate (SNARS's
        sn op-to-ev); None for the vacuous opinion, which gives nothing to believe."""

        o = self.opinion
        if o.belief == 0.0 and o.disbelief == 0.0:
            return None
        return EvidenceCounts(
            _PRIOR_WEIGHT * o.belief / o.uncertainty,
            _PRIOR_WEIGHT * o.disbelief / o.uncertainty,
            o.base_rate,
        )

    def to_dict(self) -> dict[str, Any]:
        evidence = self.evidence
        return {
            "statement": self.statement,
            "opinion": {**asdict(self.opinion), "expectation": self.opinion.expectation},
            "evidence": None if evidence is None else asdict(evidence),
        }


# am[implements a-gcje-runner]
def judged_elements(
    request: str,
    *,
    run: JudgeRun | None = None,
    timeout: float | None = None,
) -> dict[str, ElementOpinion]:
    """Each element's opinion for `request`. The judge reads the request against every statement of every element in
    one call; an element's opinion is its statement with the highest projection at the element's base rate, the first
    such statement on a tie. `run` replaces the semrewrite subprocess, as tests do; `timeout` bounds the subprocess.

    Time: one judge call over p = sum of the statement counts pairs, then p row checks."""

    if not isinstance(request, str) or not request.strip():
        raise SnarsInvalidInputError("Judged elements need a nonempty request.")
    pairs = [(request, statement) for element in ELEMENTS for statement in STATEMENTS[element]]
    rows = run(pairs) if run is not None else run_semrewrite_judge(pairs, timeout=timeout)
    if len(rows) != len(pairs):
        raise SnarsProtocolError(
            "The judge returned a different number of opinions than pairs.",
            details={"pairs": len(pairs), "opinions": len(rows)},
        )
    opinions = iter(_row_opinion(row, pair, number) for number, (row, pair) in enumerate(zip(rows, pairs), start=1))
    chosen: dict[str, ElementOpinion] = {}
    for element in ELEMENTS:
        candidates = [
            ElementOpinion(element, statement, _with_base_rate(next(opinions), BASE_RATES[element]))
            for statement in STATEMENTS[element]
        ]
        chosen[element] = max(candidates, key=lambda candidate: candidate.opinion.expectation)
    return chosen


# am[implements a-gcje-believe]
def believe_elements(
    session: SnarsSession,
    opinions: Mapping[str, ElementOpinion],
) -> dict[str, SnarsBelief]:
    """Believe each element the judge holds an opinion on, `(gc action-property "request" <element>)` at the evidence
    its opinion reads back as, from the judge's source. A vacuous opinion is skipped, as the keyword policy asserts
    nothing for a label it does not find. SNARS keeps one reading per source and statement, so a store holding another
    request would keep that request's reading and drop this one's: it is refused."""

    if set(opinions) != set(ELEMENTS):
        raise SnarsInvalidInputError(
            "Judged elements need one opinion for each element.",
            details={"expected": list(ELEMENTS), "received": sorted(opinions)},
        )
    requests = {event.payload.get("text") for event in session.store.events() if event.kind == "ingest_text"}
    if len(requests) > 1:
        raise SnarsPersistenceError(
            "Judged elements read one request per SNARS store.",
            details={
                "requests": len(requests),
                "remedy": "Use a new store for each request when GOALCHAINER_ELEMENTS=judged.",
            },
        )
    codec = session.builder.codec
    beliefs: dict[str, SnarsBelief] = {}
    for element in ELEMENTS:
        evidence = opinions[element].evidence
        if evidence is None:
            continue
        statement = codec.emit(codec.binary_statement("has-property", "request", element))
        beliefs[element] = session.believe(statement, evidence=evidence, source=SOURCE)
    return beliefs


# am[implements a-goalchainer-judged-elements.judged-path]
def elements_payload(reading: str, opinions: Mapping[str, ElementOpinion] | None) -> dict[str, Any]:
    """The decision payload's account of how the request's elements were read."""

    if opinions is None:
        return {"reading": reading}
    return {
        "reading": reading,
        "judge": JUDGE,
        "source": SOURCE,
        "trust": TRUST,
        "opinions": {element: opinions[element].to_dict() for element in ELEMENTS},
    }


# am[implements a-goalchainer-judged-elements.judged-path]
def read_request_elements(
    session: SnarsSession,
    request: str,
    reading: str,
    *,
    timeout: float | None = None,
) -> dict[str, ElementOpinion] | None:
    """Read the elements of `request`, just ingested into `session`. Under the judged reading the judge's opinions
    are believed and returned; the session must have been opened with assert_request_context false. Under the keyword
    reading the policy believes them from parsed labels in every batch, and there is nothing to return."""

    if reading != "judged":
        return None
    if session.assert_request_context:
        raise SnarsInvalidInputError(
            "Judged elements need a session that leaves the keyword assertion out.",
            details={"reading": reading},
        )
    opinions = judged_elements(request, timeout=timeout)
    believe_elements(session, opinions)
    return opinions


# am[implements a-gcje-runner]
def semrewrite_command() -> list[str]:
    """The command line that runs semrewrite: GOALCHAINER_SEMREWRITE split as a shell would split it, or semrewrite
    found on PATH."""

    configured = os.environ.get(COMMAND_VARIABLE, "")
    if configured.strip():
        try:
            return shlex.split(configured)
        except ValueError as exc:
            raise SnarsInvalidInputError(
                "GOALCHAINER_SEMREWRITE is not a command line.",
                details={"variable": COMMAND_VARIABLE, "error": str(exc)},
            ) from exc
    found = shutil.which("semrewrite")
    if found is None:
        raise SnarsDependencyUnavailableError(
            "The semantic rewriter is unavailable for judged elements.",
            details={
                "variable": COMMAND_VARIABLE,
                "remedy": (
                    "Set GOALCHAINER_SEMREWRITE to a command that runs semrewrite, such as "
                    "'python -m semrewrite.cli' in its environment, or put semrewrite on PATH."
                ),
            },
        )
    return [found]


# am[implements a-gcje-runner]
def run_semrewrite_judge(
    pairs: Sequence[tuple[str, str]],
    *,
    timeout: float | None = None,
) -> list[Any]:
    """Run `semrewrite judge` on (premise, conclusion) pairs and return its JSON rows in order: each opinion at the
    reported base rate, discounted by the judge's trust. Any failure is an error, never a reading of fewer elements."""

    command = [
        *semrewrite_command(),
        "judge",
        "--judge",
        JUDGE,
        "--trust",
        repr(TRUST),
        "--base-rate",
        repr(_REPORTED_BASE_RATE),
    ]
    lines = "".join(json.dumps({"premise": p, "conclusion": c}) + "\n" for p, c in pairs)
    try:
        result = subprocess.run(
            command,
            input=lines,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SnarsTimeoutError(
            "The semantic rewriter's judge did not finish in time.",
            details={"command": command, "timeout_seconds": timeout},
        ) from exc
    except OSError as exc:
        raise SnarsDependencyUnavailableError(
            "The semantic rewriter's judge cannot be started.",
            details={"command": command, "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if result.returncode != 0:
        raise SnarsDependencyUnavailableError(
            "The semantic rewriter's judge failed.",
            details={"command": command, "returncode": result.returncode, "stderr": result.stderr[-2000:]},
        )
    rows: list[Any] = []
    for number, line in enumerate(result.stdout.splitlines(), start=1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SnarsProtocolError(
                "The semantic rewriter's judge wrote a line that is not JSON.",
                details={"line": number, "error": str(exc)},
            ) from exc
    return rows


# am[implements a-gcje-runner]
def _row_opinion(row: Any, pair: tuple[str, str], number: int) -> SubjectiveOpinion:
    """One judge row as the opinion it states, checked against the pair it answers and the judge's calibration: its
    uncertainty is at least 1 - TRUST, which discounting by TRUST guarantees."""

    def refuse(reason: str) -> SnarsProtocolError:
        return SnarsProtocolError(
            f"The judge's opinion {number} {reason}.",
            details={"row": number, "premise": pair[0], "conclusion": pair[1]},
        )

    if not isinstance(row, Mapping):
        raise refuse("is not a JSON object")
    if row.get("premise") != pair[0] or row.get("conclusion") != pair[1]:
        raise refuse("answers a different pair")
    numbers: dict[str, float] = {}
    for name in ("belief", "disbelief", "uncertainty", "base_rate"):
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= value <= 1.0:
            raise refuse(f"has no {name} in [0, 1]")
        numbers[name] = float(value)
    belief, disbelief = numbers["belief"], numbers["disbelief"]
    if not math.isclose(belief + disbelief + numbers["uncertainty"], 1.0, rel_tol=0.0, abs_tol=_ROUNDING):
        raise refuse("does not sum to one")
    if not math.isclose(numbers["base_rate"], _REPORTED_BASE_RATE, rel_tol=0.0, abs_tol=_ROUNDING):
        raise refuse(f"is not at base rate {_REPORTED_BASE_RATE}")
    uncertainty = 1.0 - belief - disbelief
    if uncertainty < 1.0 - TRUST - _ROUNDING:
        raise refuse(f"is not discounted by trust {TRUST}")
    return SubjectiveOpinion(belief, disbelief, uncertainty, _REPORTED_BASE_RATE)


# am[rests-on c-gcje-rebase-exact]
def _with_base_rate(opinion: SubjectiveOpinion, base_rate: float) -> SubjectiveOpinion:
    return SubjectiveOpinion(opinion.belief, opinion.disbelief, opinion.uncertainty, base_rate)


__all__ = [
    "BASE_RATES",
    "COMMAND_VARIABLE",
    "ELEMENTS",
    "JUDGE",
    "READINGS",
    "READING_VARIABLE",
    "SOURCE",
    "STATEMENTS",
    "TRUST",
    "ElementOpinion",
    "believe_elements",
    "elements_payload",
    "judged_elements",
    "read_request_elements",
    "run_semrewrite_judge",
    "selected_reading",
    "semrewrite_command",
]
