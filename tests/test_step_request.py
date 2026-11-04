"""Purpose: verify the step-request verdict (goal_chainer.step_request): the facts a well-formed step-request gives and
every malformed one it refuses, the packaged creative-controller norms on pymetta's lib_deontic for each of the
controller's rules, a differential check against an oracle written from the rules' text alone over generated
step-requests, the refusal of a norm set lib_deontic would partly skip, and the wire, CLI and skill surfaces."""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from goal_chainer.cli import main as cli_main
from goal_chainer.deontic_engine import DeonticOutputError
from goal_chainer.errors import InvalidInputError
from goal_chainer.omegaclaw_skill import run_skill
from goal_chainer.runtime.budget import RunBudget
from goal_chainer.step_request import norms_text, packaged_norm_names, run_step_request, step_facts, verdict

HEAD = "(op render-job op-17 job-3) (generation s1 r1 t1 c1) (context task-9 maya studio critic-a blender hq)"
_, NORMS = norms_text({"packaged": "creative-controller"})


# am[related a-gc-step-request-1104]
def _step(target="(target provider claude)", leaves="(h1 image CC-BY-4.0)", cost="(cost 4 10 usd)", facts="(facts)"):
    return f"(step-request {HEAD} {target} (leaves {leaves}) {cost} {facts})"


# am[related a-gc-step-request-1104]
def _budget():
    return RunBudget(inference_budget=10**10, timeout_seconds=1200)


# am[verifies a-gc-step-request-1104]
def test_a_step_request_gives_each_clause_as_a_fact_and_the_exact_destination():
    text = _step(target="(target pool host-3 trusted)",
                 leaves='(h1 image CC-BY-4.0) ("sha256:ab" audio own (unreleased (private maya)))',
                 cost="(cost 12.5 10 usd)", facts="(facts ((scene-final c1) unverified ev-9))")
    assert step_facts(text) == (
        "(op render-job op-17 job-3)", "(generation s1 r1 t1 c1)", "(context task-9 maya studio critic-a blender hq)",
        "(target pool host-3 trusted)", "(sends-to host-3)",
        "(leaf h1 image CC-BY-4.0)", '(leaf "sha256:ab" audio own)', '(unreleased "sha256:ab")',
        '(private "sha256:ab" maya)',
        "(cost 12.5 10 usd)", "(over-budget 12.5 10 usd)",
        "(fact (scene-final c1) unverified ev-9)")


# am[verifies a-gc-step-request-1104]
def test_a_cost_at_the_budget_left_is_not_over_it():
    assert "(over-budget 10 10 usd)" not in step_facts(_step(cost="(cost 10 10 usd)"))
    assert "(over-budget 10.5 10 usd)" in step_facts(_step(cost="(cost 10.5 10 usd)"))


MALFORMED = {
    "two forms": _step() + " (x)",
    "a directive": "!" + _step(),
    "unreadable": _step()[:-1],
    "another head": _step().replace("step-request", "step"),
    "a missing clause": f"(step-request {HEAD} (target provider claude) (leaves) (cost 1 2 usd))",
    "a clause twice": _step(facts="(facts) (facts)"),
    "an unknown clause": _step(facts="(facts) (colour red)"),
    "an op of two items": _step().replace("(op render-job op-17 job-3)", "(op render-job op-17)"),
    "a target of another kind": _step(target="(target cloud x)"),
    "a pool class it doesn't know": _step(target="(target pool host-3 partner)"),
    "a provider with a class": _step(target="(target provider claude trusted)"),
    "a leaf of two items": _step(leaves="(h1 image)"),
    "a leaf named twice": _step(leaves="(h1 image MIT) (h1 audio MIT)"),
    "a tag it doesn't know": _step(leaves="(h1 image MIT (draft))"),
    "tags that aren't a list": _step(leaves="(h1 image MIT unreleased)"),
    "a fact of another status": _step(facts="(facts ((x) maybe ev-1))"),
    "a negative estimate": _step(cost="(cost -1 10 usd)"),
    "a cost that isn't a number": _step(cost="(cost lots 10 usd)"),
    "an infinite budget": _step(cost="(cost 1 inf usd)"),
    "a variable": _step(leaves="($h image MIT)"),
    "a pattern variable in a fact": _step(facts="(facts ((x ?y) verified ev-1))"),
}


# am[verifies a-gc-step-request-1104]
@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_a_malformed_step_request_is_refused_whole(case):
    with pytest.raises(InvalidInputError):
        step_facts(MALFORMED[case])


# The packaged norm sets are the files of goal_chainer/norms, named as packaged domains are.
# am[verifies a-gc-step-request-1104] am[verifies a-gc-step-norms-packaged-1104]
def test_norms_are_selected_by_packaged_name_or_path(tmp_path):
    assert packaged_norm_names() == ("creative-controller",)
    assert norms_text({"packaged": "creative-controller"})[1] == NORMS
    with pytest.raises(InvalidInputError) as unknown:
        norms_text({"packaged": "nobody"})
    assert unknown.value.details == {"packaged": ["creative-controller"]}
    path = tmp_path / "norms.metta"
    path.write_text("(given (open-licence own))\n", encoding="utf-8")
    assert norms_text({"path": str(path)}) == (str(path), "(given (open-licence own))\n")
    for selection in ({"packaged": "nobody"}, {"packaged": "creative-controller", "path": str(path)}, {"other": "x"},
                      {"path": str(tmp_path / "missing.metta")}, "creative-controller"):
        with pytest.raises(InvalidInputError):
            norms_text(selection)


# Each of the controller's rules, alone and where two meet, with the verdict atom the controller reads.
VERDICTS = {
    "an open asset goes anywhere, its attribution with it": (
        _step(),
        "(verdict permitted ((licence-open (send h1 outside-model)) "
        "(attribution-travels (attribution h1 CC-BY-4.0))) ())"),
    "a non-commercial asset never goes to an outside model": (
        _step(leaves="(h1 image CC-BY-4.0) (h2 audio CC-BY-NC-4.0)"),
        "(verdict forbidden ((licence-restricted (send h2 outside-model))) ())"),
    "a restricted asset may go to a trusted host": (
        _step(target="(target pool host-3 trusted)", leaves="(h2 audio CC-BY-NC-4.0)"),
        "(verdict permitted ((licence-restricted-trusted (send h2 trusted-host))) ())"),
    "a pool host no one classed is open": (
        _step(target="(target pool host-3)", leaves="(h2 audio proprietary)"),
        "(verdict forbidden ((licence-restricted (send h2 open-host))) ())"),
    "an unknown licence is restricted": (
        _step(leaves="(h2 audio unknown)"),
        "(verdict forbidden ((licence-restricted (send h2 outside-model))) ())"),
    "unreleased work stays on own or trusted machines whatever its licence": (
        _step(leaves="(h1 image CC-BY-4.0 (unreleased))"),
        "(verdict forbidden ((unreleased-trusted-only (send h1 outside-model))) ())"),
    "private material waits for its owner's consent": (
        _step(leaves="(h3 photo own ((private maya)))"),
        "(verdict obligated ((private-needs-consent (consent maya h3 claude))) ())"),
    "consent for the exact destination lets it go": (
        _step(leaves="(h3 photo own ((private maya)))", facts="(facts ((consent maya h3 claude) verified ev-1))"),
        "(verdict permitted ((licence-open (send h3 outside-model)) (consent-shown (consented maya h3 claude))) (ev-1))"),
    "consent for another destination does not": (
        _step(leaves="(h3 photo own ((private maya)))", facts="(facts ((consent maya h3 gemini) verified ev-1))"),
        "(verdict obligated ((private-needs-consent (consent maya h3 claude))) ())"),
    "private material on the hive's own machine needs no consent": (
        _step(target="(target pool box-1 own)", leaves="(h3 photo own ((private maya)))"),
        "(verdict permitted ((licence-open (send h3 own-machine))) ())"),
    "private material waits for consent on a trusted host too": (
        _step(target="(target pool host-3 trusted)", leaves="(h3 photo own ((private maya)))"),
        "(verdict obligated ((private-needs-consent (consent maya h3 host-3))) ())"),
    "a cost over the budget left is forbidden for automatic dispatch": (
        _step(target="(target pool box-1 own)", leaves="(h1 image MIT)", cost="(cost 12.5 10 usd)"),
        "(verdict forbidden ((budget-over-left (auto-dispatch 12.5 10 usd))) ())"),
    "an unverified fact is verified first": (
        _step(target="(target pool box-1 own)", leaves="(h1 image MIT)",
              facts="(facts ((scene-final c1) unverified ev-9))"),
        "(verdict obligated ((verify-first (verify (scene-final c1)))) (ev-9))"),
    "the strictest rule wins": (
        _step(leaves="(h2 audio CC-BY-NC-4.0)", facts="(facts ((scene-final c1) unverified ev-9))"),
        "(verdict forbidden ((licence-restricted (send h2 outside-model))) ())"),
    "a step that sends nothing and fits its budget is permitted": (
        _step(leaves=""),
        "(verdict permitted () ())"),
}


# am[verifies a-gc-step-request-1104]
@pytest.mark.parametrize("case", sorted(VERDICTS))
def test_each_rule_gives_the_verdict_the_controller_reads(case):
    text, expected = VERDICTS[case]
    assert verdict(text, NORMS, budget=_budget()).atom() == expected


# The oracle reads the controller's rules as physixCN wrote them (omegahive#11, comment 6607935015) and nothing of
# the norm set: where a step's leaves may go, what waits for consent or verification, and what the budget forbids.
OPEN = {"own", "CC0", "CC0-1.0", "MIT", "Apache-2.0", "BSD", "BSD-2-Clause", "BSD-3-Clause",
        *(f"CC-BY{sa}{version}" for sa in ("", "-SA") for version in ("", "-1.0", "-2.0", "-2.5", "-3.0", "-4.0"))}
LICENCES = ["own", "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-3.0", "MIT", "Apache-2.0", "BSD-3-Clause",
            "CC-BY-NC-4.0", "CC-BY-ND-4.0", "CC-BY-NC-SA-4.0", "proprietary", "unknown"]
DESTINATIONS = {("provider", None): "outside-model", ("pool", "own"): "own-machine",
                ("pool", "trusted"): "trusted-host", ("pool", "open"): "open-host", ("pool", None): "open-host"}


# am[related a-gc-step-request-1104] am[rests-on c-gc-step-rules-1104]
def _oracle(kind, cls, where, leaves, estimate, left, facts):
    """(status, {literal: rules that may name it}, evidence refs) for a step, from the rules' text."""
    destination = DESTINATIONS[(kind, cls)]
    untrusted = destination in ("outside-model", "open-host")
    forbidden, obligated, permitted, evidence = {}, {}, {}, {"obligated": [], "permitted": []}
    for name, licence, unreleased, owner in leaves:
        send = f"(send {name} {destination})"
        restricted = licence not in OPEN
        rules = {*(["licence-restricted"] if restricted and untrusted else []),
                 *(["unreleased-trusted-only"] if unreleased and untrusted else [])}
        if rules:
            forbidden[send] = rules
        else:
            permitted[send] = {"licence-restricted-trusted" if restricted else "licence-open"}
        if licence.startswith("CC-BY") and licence in OPEN:
            permitted[f"(attribution {name} {licence})"] = {"attribution-travels"}
        if owner and destination != "own-machine":
            consent = f"(consent {owner} {name} {where})"
            ref = next((r for fact, status, r in facts if fact == consent and status == "verified"), None)
            if ref is None:
                obligated[consent] = {"private-needs-consent"}
            else:
                permitted[f"(consented {owner} {name} {where})"] = {"consent-shown"}
                evidence["permitted"].append(ref)
    if estimate > left:
        forbidden[f"(auto-dispatch {estimate} {left} usd)"] = {"budget-over-left"}
    for fact, status, ref in facts:
        if status == "unverified":
            obligated[f"(verify {fact})"] = {"verify-first"}
            evidence["obligated"].append(ref)
    if forbidden:
        return "forbidden", forbidden, []
    if obligated:
        return "obligated", obligated, evidence["obligated"]
    return "permitted", permitted, evidence["permitted"]


_leaves = st.lists(st.tuples(st.sampled_from(LICENCES), st.booleans(), st.sampled_from([None, "maya", "ola"])),
                   max_size=3)
# One fact per name: a fact given twice is one literal the engine supports with one of its refs.
_facts = st.lists(st.tuples(st.sampled_from(["(scene-final c1)", "(rights-cleared a0)", "consent"]),
                            st.sampled_from(["verified", "unverified"])), max_size=3, unique_by=lambda fact: fact[0])


# am[verifies a-gc-step-request-1104]
@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(target=st.sampled_from(sorted(DESTINATIONS, key=str)), leaves=_leaves,
       estimate=st.sampled_from([0, 4, 10, 12]), facts=_facts, consent_for=st.sampled_from(["claude", "host-3"]))
def test_the_norms_agree_with_the_rules_as_written(target, leaves, estimate, facts, consent_for):
    kind, cls = target
    where = "claude" if kind == "provider" else "host-3"
    named = [(f"a{i}", licence, unreleased, owner) for i, (licence, unreleased, owner) in enumerate(leaves)]
    owners = [(name, owner) for name, _, _, owner in named if owner]
    written = []
    for i, (fact, status) in enumerate(facts):
        if fact == "consent":
            if not owners:
                continue
            name, owner = owners[i % len(owners)]
            fact = f"(consent {owner} {name} {consent_for})"
        written.append((fact, status, f"ev-{i}"))
    target_text = f"(target {kind} {where}{'' if cls is None else ' ' + cls})"
    leaf_text = " ".join(
        f"({name} image {licence}"
        + ("" if not (unreleased or owner) else
           " (" + " ".join([*(["unreleased"] if unreleased else []), *([f"(private {owner})"] if owner else [])]) + ")")
        + ")" for name, licence, unreleased, owner in named)
    fact_text = " ".join(f"({fact} {status} {ref})" for fact, status, ref in written)
    text = _step(target=target_text, leaves=leaf_text, cost=f"(cost {estimate} 10 usd)", facts=f"(facts {fact_text})")
    status, reasons, evidence = _oracle(kind, cls, where, named, estimate, 10, written)
    answer = verdict(text, NORMS, budget=_budget())
    assert answer.status == status, text
    assert {literal for _, literal in answer.reasons} == set(reasons), text
    assert all(rule in reasons[literal] for rule, literal in answer.reasons), text
    assert sorted(answer.evidence) == sorted(set(evidence)), text


# am[verifies a-gc-step-request-1104] am[rests-on c-gc-step-engine-forms-1104]
def test_a_norm_set_lib_deontic_would_partly_skip_is_refused():
    nested = NORMS + "(normally nested (and (leaf ?h ?k ?l) (and (sends-to ?w) (sends-to ?w))) (must (verify ?h)))\n"
    with pytest.raises(DeonticOutputError, match="skipped"):
        verdict(_step(), nested, budget=_budget())


# am[verifies a-gc-step-request-1104]
def test_the_wire_answer_is_advisory_and_refuses_other_fields():
    answer = run_step_request({"step_request": _step(), "norms": {"packaged": "creative-controller"}},
                              budget=_budget())
    assert answer["protocol"] == "goalchainer-step-request-v1" and answer["norms"] == "creative-controller"
    assert answer["verdict"] == VERDICTS["an open asset goes anywhere, its attribution with it"][1]
    assert answer["authorization"] == "unresolved" and answer["applies_effects"] is False
    assert answer["reasons"][0] == {"rule": "licence-open", "literal": "(send h1 outside-model)"}
    assert answer["inferences"] > 0 and answer["support"][0]["label"] == "licence-open"
    for payload in ({"step_request": _step()}, {"step_request": "", "norms": {"packaged": "creative-controller"}},
                    {"step_request": _step(), "norms": {"packaged": "creative-controller"}, "extra": 1}):
        with pytest.raises(InvalidInputError):
            run_step_request(payload, budget=_budget())


# am[verifies a-gc-step-request-1104]
def test_the_cli_and_the_skill_answer_the_same_verdict(tmp_path, capsys):
    request = {"step_request": _step(leaves="(h2 audio CC-BY-NC-4.0)"), "norms": {"packaged": "creative-controller"}}
    path = tmp_path / "step.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    assert cli_main(["step", "--input", str(path), "--inference-budget", str(10**10), "--timeout-seconds", "600"]) == 0
    printed = json.loads(capsys.readouterr().out)
    skill = run_skill("goalchainer-step-request",
                      json.dumps({**request, "inference_budget": 10**10, "timeout_seconds": 600}))
    expected = "(verdict forbidden ((licence-restricted (send h2 outside-model))) ())"
    assert printed["verdict"] == skill["verdict"] == expected and skill["skill"] == "goalchainer-step-request"
