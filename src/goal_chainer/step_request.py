"""Purpose: answer a creative controller's step-request with one verdict atom, by running the request's clauses as
facts against a norm set on lib_deontic and reading the verdict, the rule behind each reason and the evidence it
rests on from what the engine proved and its support.

physixCN's controller (omegahive#11) asks before it dispatches a step that leaves the hive or costs money:

    (step-request
      (op KIND OP-ID REF)
      (generation STORY-HASH RULES-HASH TIMELINE-HASH SCENE-HASH)
      (context TASK-ID PERSON MAKER CRITIC-FAMILY ENGINE PROFILE)
      (target pool WHERE) or (target pool WHERE CLASS) or (target provider WHERE)
      (leaves (HASH KIND LICENCE) ...)                 each leaf may add a fourth item, (TAG ...)
      (cost ESTIMATE BUDGET-LEFT UNIT)
      (facts (FACT verified REF) (FACT unverified REF) ...))

CLASS says what a pool host is, own (one of the hive's own machines), trusted (enrolled by a person) or open; a leaf's
tags are unreleased and (private PERSON). It reads back one atom,

    (verdict STATUS (REASON ...) (EVIDENCE-REF ...))

STATUS forbidden when the norms forbid any part of the step, else obligated when a duty must be met first, which the
controller reads as wait until it holds, else permitted. Each REASON is (RULE LITERAL), the label of the norm that
concluded LITERAL, so `(licence-restricted (send h2 outside-model))` or `(verify-first (verify (scene-final s1)))`;
the evidence refs are those of the request's facts the reasons' support rests on. The verdict is advisory: the
controller's own gates decide, and nothing here authorizes or performs a dispatch.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from .deontic_engine import DeonticLiteral, DeonticOutputError, DeonticRun, DeonticSupport, run_deontic_theory
from .errors import InvalidInputError
from .runtime.budget import RunBudget, caller_budget
from .sexpr.forms import MettaTextError, top_level_forms
from .sexpr.syntax import Atom, StringLiteral, Symbol, emit, parse

STEP_REQUEST_PROTOCOL = "goalchainer-step-request-v1"

# Packaged norm sets are the files of goal_chainer/norms, found and named as packaged domains are (domains.loader):
# creative_controller.metta is creative-controller, so a norm set ships as one file there.
# am[implements a-gc-step-request-1104] am[implements a-gc-step-norms-packaged-1104]
NORMS_DIRECTORY = "norms"

# Each clause a step-request carries, once, with the arity of its arguments; leaves and facts take any number of
# items. The target's arity depends on its kind, so it is checked apart.
# am[implements a-gc-step-request-1104] am[rests-on c-gc-step-shape-1104]
CLAUSE_ARITY = {"op": 3, "generation": 4, "context": 6, "target": None, "leaves": None, "cost": 3, "facts": None}
POOL_CLASSES = ("own", "trusted", "open")
FACT_STATUSES = ("verified", "unverified")

# The forms of a lib_deontic theory that become one ingested rule each (DeonticRun.rules); prefer only ranks them.
_RULE_FORMS = frozenset({"given", "normally", "always", "except"})
_THEORY_FORMS = _RULE_FORMS | {"prefer"}
# Proved non-deontic literals a permitted verdict reports beside its permissions.
_NOTES = frozenset({"attribution", "consented"})

__all__ = ["STEP_REQUEST_PROTOCOL", "StepVerdict", "packaged_norm_names", "run_step_request", "step_facts", "verdict"]


# am[implements a-gc-step-request-1104]
@dataclass(frozen=True, slots=True)
class StepVerdict:
    """A step-request's verdict: its status, each reason as (rule label, literal text) in the order the engine
    proved them, the evidence refs those reasons rest on, their support trees and the review they came from."""

    status: str
    reasons: tuple[tuple[str, str], ...]
    evidence: tuple[str, ...]
    support: tuple[DeonticSupport, ...]
    run: DeonticRun

    def atom(self) -> str:
        reasons = " ".join(f"({label} {literal})" for label, literal in self.reasons)
        return f"(verdict {self.status} ({reasons}) ({' '.join(self.evidence)}))"

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.atom(),
            "status": self.status,
            "reasons": [{"rule": label, "literal": literal} for label, literal in self.reasons],
            "evidence": list(self.evidence),
            "support": [node.to_dict() for node in self.support],
        }


# The wire request: {"step_request": TEXT, "norms": {"packaged": NAME} or {"path": FILE}}, the limits in the CLI's or
# the skill's envelope, as every v2 request takes them.
# Time: the step-request's parse, linear in its text, plus one bounded review of the norms with its facts.
# am[implements a-gc-step-request-1104]
def run_step_request(payload: object, *, budget: RunBudget) -> dict[str, Any]:
    """The verdict on one step-request under `budget`, as the CLI and the skill answer it."""

    budget = caller_budget(budget, "a step-request")
    budget.remaining()
    before = budget.spent
    if not isinstance(payload, Mapping) or set(payload) != {"step_request", "norms"}:
        raise InvalidInputError("A step-request is a JSON object with exactly step_request and norms.")
    text = payload["step_request"]
    if not isinstance(text, str) or not text.strip():
        raise InvalidInputError("step_request must be the step-request atom's MeTTa text.")
    name, norms = norms_text(payload["norms"])
    result = verdict(text, norms, budget=budget)
    budget.remaining()
    return {
        "protocol": STEP_REQUEST_PROTOCOL,
        "norms": name,
        **result.to_dict(),
        "inferences": budget.spent - before,
        "authorization": "unresolved",
        "applies_effects": False,
    }


# am[implements a-gc-step-request-1104]
def norms_text(selection: object) -> tuple[str, str]:
    """A norm set's name and theory text, from {"packaged": NAME} or {"path": FILE}."""

    if not isinstance(selection, Mapping) or len(selection) != 1 or set(selection) - {"packaged", "path"}:
        raise InvalidInputError("norms must select exactly one packaged name or path.")
    ((key, name),) = selection.items()
    if not isinstance(name, str) or not name.strip():
        raise InvalidInputError(f"norms.{key} must be nonempty text.")
    if key == "packaged":
        packaged = packaged_norm_names()
        if name not in packaged:
            raise InvalidInputError(f"Unknown packaged norms: {name}", details={"packaged": list(packaged)})
        source: Path | Traversable = _norms_directory() / (name.replace("-", "_") + ".metta")
    else:
        source = Path(name).expanduser()
    try:
        return name, source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InvalidInputError(f"Cannot read the norms: {error}", details={key: name}) from error


# am[implements a-gc-step-norms-packaged-1104]
def packaged_norm_names() -> tuple[str, ...]:
    """The norm sets shipped inside the package, the files of `norms/`, named as a request selects them."""

    return tuple(sorted(entry.name.removesuffix(".metta").replace("_", "-")
                        for entry in _norms_directory().iterdir() if entry.name.endswith(".metta")))


# am[implements a-gc-step-norms-packaged-1104]
def _norms_directory() -> Traversable:
    return resources.files("goal_chainer").joinpath(NORMS_DIRECTORY)


# The theory is the norms' forms with the step's facts after them, comments dropped, and the review must ingest one
# rule per given, normally, always and except form: lib_deontic skips a form it cannot read, a nested and among them,
# and only warns, so a count short of the forms is an error here, never a norm that silently stops applying.
# Time: one bounded review, then one pass over its conclusions and their support trees.
# am[implements a-gc-step-request-1104] am[rests-on c-gc-step-engine-forms-1104]
def verdict(step_request: str, norms: str, *, budget: RunBudget) -> StepVerdict:
    """The verdict lib_deontic gives `step_request` under `norms`. Raises InvalidInputError for a malformed
    step-request or norm set, and DeonticOutputError when the engine skipped a form or left a dilemma, which
    a consistent norm set never does."""

    norm_forms = _theory_forms(norms, "the norms")
    facts = step_facts(step_request)
    forms = [*norm_forms, *(f"(given {fact})" for fact in facts)]
    run = run_deontic_theory("\n".join(forms) + "\n", budget=budget)
    expected = sum(1 for form in forms if _head(form) in _RULE_FORMS)
    if run.rules != expected:
        raise DeonticOutputError(
            f"lib_deontic ingested {run.rules} rules of the theory's {expected}; a form it could not read was skipped",
            details={"ingested": run.rules, "expected": expected})
    if run.dilemmas:
        raise DeonticOutputError("The norms leave a dilemma, so no verdict is settled.",
                                 details={"dilemmas": [literal.render() for literal in run.dilemmas]})
    return _read_verdict(run)


# Every clause is checked before any fact is written, so a step-request the norms would misread is refused whole.
# Time and space: linear in the step-request's text.
# am[implements a-gc-step-request-1104] am[rests-on c-gc-step-shape-1104]
def step_facts(text: str) -> tuple[str, ...]:
    """The facts a step-request gives the norms, as MeTTa text, in its clauses' order. Raises InvalidInputError
    naming what is wrong with a malformed one."""

    request = _one_atom(text)
    if not isinstance(request, list) or not request or request[0] != Symbol("step-request"):
        raise InvalidInputError("A step-request is one (step-request CLAUSE ...) expression.")
    clauses: dict[str, list[Atom]] = {}
    for clause in request[1:]:
        if not isinstance(clause, list) or not clause or not isinstance(clause[0], Symbol):
            raise InvalidInputError(f"Each clause of a step-request is (NAME ...), not {emit(clause)}.")
        name = clause[0].text
        if name not in CLAUSE_ARITY:
            raise InvalidInputError(f"Unknown step-request clause: {name}", details={"clauses": sorted(CLAUSE_ARITY)})
        if name in clauses:
            raise InvalidInputError(f"The step-request gives {name} twice.")
        arity = CLAUSE_ARITY[name]
        if arity is not None and len(clause) - 1 != arity:
            raise InvalidInputError(f"({name} ...) takes {arity} items, not {len(clause) - 1}.")
        for item in clause[1:]:
            _data(item, name)
        clauses[name] = clause[1:]
    missing = sorted(set(CLAUSE_ARITY) - set(clauses))
    if missing:
        raise InvalidInputError(f"The step-request lacks {', '.join(missing)}.", details={"missing": missing})

    facts = [emit([Symbol(name), *clauses[name]]) for name in ("op", "generation", "context")]
    facts += _target_facts(clauses["target"])
    facts += _leaf_facts(clauses["leaves"])
    facts += _cost_facts(clauses["cost"])
    facts += _fact_facts(clauses["facts"])
    return tuple(facts)


# am[implements a-gc-step-request-1104]
def _target_facts(items: list[Atom]) -> list[str]:
    kind = items[0] if items else None
    if kind == Symbol("provider") and len(items) == 2 and isinstance(items[1], Symbol | StringLiteral):
        pass
    elif kind == Symbol("pool") and len(items) in (2, 3) and isinstance(items[1], Symbol | StringLiteral):
        if len(items) == 3 and items[2] not in [Symbol(name) for name in POOL_CLASSES]:
            raise InvalidInputError(f"A pool host's class is one of {', '.join(POOL_CLASSES)}, not {emit(items[2])}.")
    else:
        raise InvalidInputError("target is (target pool WHERE), (target pool WHERE CLASS) or (target provider WHERE).")
    return [emit([Symbol("target"), *items]), emit([Symbol("sends-to"), items[1]])]


# am[implements a-gc-step-request-1104]
def _leaf_facts(items: list[Atom]) -> list[str]:
    facts, seen = [], set()
    for leaf in items:
        if not isinstance(leaf, list) or len(leaf) not in (3, 4) or not all(
                isinstance(part, Symbol | StringLiteral) for part in leaf[:3]):
            raise InvalidInputError(f"A leaf is (HASH KIND LICENCE) or (HASH KIND LICENCE (TAG ...)), not {emit(leaf)}.")
        content = emit(leaf[0])
        if content in seen:
            raise InvalidInputError(f"The leaves name {content} twice.")
        seen.add(content)
        facts.append(emit([Symbol("leaf"), *leaf[:3]]))
        tags = leaf[3] if len(leaf) == 4 else []
        if not isinstance(tags, list):
            raise InvalidInputError(f"A leaf's tags are a list, (TAG ...), not {emit(tags)}.")
        for tag in tags:
            if tag == Symbol("unreleased"):
                facts.append(emit([Symbol("unreleased"), leaf[0]]))
            elif (isinstance(tag, list) and len(tag) == 2 and tag[0] == Symbol("private")
                  and isinstance(tag[1], Symbol | StringLiteral)):
                facts.append(emit([Symbol("private"), leaf[0], tag[1]]))
            else:
                raise InvalidInputError(f"A leaf's tag is unreleased or (private PERSON), not {emit(tag)}.")
    return facts


# am[implements a-gc-step-request-1104]
def _cost_facts(items: list[Atom]) -> list[str]:
    estimate, left = (_amount(item, what) for item, what in zip(items, ("estimate", "budget-left")))
    if not isinstance(items[2], Symbol):
        raise InvalidInputError(f"The cost's unit is a symbol, not {emit(items[2])}.")
    cost = [Symbol("cost"), *items]
    return [emit(cost)] + ([emit([Symbol("over-budget"), *items])] if estimate > left else [])


# am[implements a-gc-step-request-1104]
def _fact_facts(items: list[Atom]) -> list[str]:
    facts = []
    for item in items:
        if (not isinstance(item, list) or len(item) != 3 or item[1] not in [Symbol(s) for s in FACT_STATUSES]
                or not isinstance(item[2], Symbol | StringLiteral)):
            raise InvalidInputError(f"A fact is (FACT verified REF) or (FACT unverified REF), not {emit(item)}.")
        facts.append(emit([Symbol("fact"), *item]))
    return facts


# A cost figure is a finite number at least 0, written as the request's own symbol so the fact keeps its spelling.
# am[implements a-gc-step-request-1104]
def _amount(item: Atom, what: str) -> float:
    try:
        value = float(item.text) if isinstance(item, Symbol) else None
    except ValueError:
        value = None
    if value is None or value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise InvalidInputError(f"The cost's {what} is a number at least 0, not {emit(item)}.")
    return value


# A request's atoms are data: a variable would turn a fact into a pattern every rule could match.
# Time: linear in the atom's size.
# am[implements a-gc-step-request-1104]
def _data(atom: Atom, clause: str) -> None:
    if isinstance(atom, Symbol) and atom.text[:1] in ("$", "?"):
        raise InvalidInputError(f"A step-request holds data, not the variable {atom.text}, in ({clause} ...).")
    if isinstance(atom, list):
        for item in atom:
            _data(item, clause)


# am[implements a-gc-step-request-1104]
def _one_atom(text: str) -> Atom:
    try:
        forms = list(top_level_forms(text))
    except MettaTextError as error:
        raise InvalidInputError(f"The step-request is not readable MeTTa: {error}") from error
    if len(forms) != 1 or forms[0].directive:
        raise InvalidInputError("The step-request is exactly one expression.")
    try:
        return parse(forms[0].text)
    except ValueError as error:
        raise InvalidInputError(f"The step-request is not readable MeTTa: {error}") from error


# Time: one pass over the theory's text.
# am[implements a-gc-step-request-1104]
def _theory_forms(text: str, where: str) -> list[str]:
    try:
        forms = [form.text for form in top_level_forms(text)]
    except MettaTextError as error:
        raise InvalidInputError(f"{where} are not readable MeTTa: {error}") from error
    unknown = sorted({_head(form) for form in forms} - _THEORY_FORMS)
    if unknown:
        raise InvalidInputError(f"{where} may use {', '.join(sorted(_THEORY_FORMS))}, not {', '.join(unknown)}.")
    return forms


# am[implements a-gc-step-request-1104]
def _head(form: str) -> str:
    atom = parse(form)
    return atom[0].text if isinstance(atom, list) and atom and isinstance(atom[0], Symbol) else ""


# The verdict is the strictest status the proved literals settle: any prohibition forbids the step, else any duty
# makes it wait, else it is permitted. A permitted step's reasons are its permissions and what the norms note about
# it, attribution and consent; each reason's label is the rule its support tree names.
# Time: one pass over the conclusions and the reasons' support trees.
# am[implements a-gc-step-request-1104]
def _read_verdict(run: DeonticRun) -> StepVerdict:
    supported = {node.literal: node for node in run.support}
    proved = [conclusion.literal for conclusion in run.conclusions if conclusion.is_provable]
    by_mode = {mode: [literal for literal in proved if literal.mode == mode] for mode in ("F", "O", "P")}
    if by_mode["F"]:
        status, literals = "forbidden", by_mode["F"]
    elif by_mode["O"]:
        status, literals = "obligated", by_mode["O"]
    else:
        status = "permitted"
        literals = [literal for literal in by_mode["P"] if literal.functor == "send"]
        literals += [literal for literal in proved if literal.mode == "none" and literal.functor in _NOTES]
    support = tuple(_rule(supported, literal) for literal in literals)
    reasons = tuple((node.label or "", _content(node.literal)) for node in support)
    evidence = tuple(dict.fromkeys(ref for node in support for ref in _refs(node)))
    return StepVerdict(status, reasons, evidence, support, run)


# A reason is a rule's conclusion: a literal the engine proved with no rule behind it is a norm set's fact, which
# names no rule a controller could read.
# am[implements a-gc-step-request-1104]
def _rule(supported: Mapping[DeonticLiteral, DeonticSupport], literal: DeonticLiteral) -> DeonticSupport:
    node = supported.get(literal)
    if node is None or node.kind != "rule" or not node.label:
        raise DeonticOutputError(f"lib_deontic proved {literal.render()} with no rule's support.",
                                 details={"literal": literal.render()})
    return node


# am[implements a-gc-step-request-1104]
def _content(literal: DeonticLiteral) -> str:
    return f"({literal.functor}{''.join(' ' + arg for arg in literal.args)})"


# The refs of the request's facts a support tree rests on, (fact FACT STATUS REF), in the order the tree reaches them.
# Time: linear in the tree's size.
# am[implements a-gc-step-request-1104]
def _refs(node: DeonticSupport):
    if node.literal.functor == "fact" and len(node.literal.args) == 3:
        yield node.literal.args[2]
    for premise in node.premises:
        yield from _refs(premise)
