"""Purpose: verify the step-request verdict (goal_chainer.step_request): the facts a well-formed step-request gives and
every malformed one it refuses, the packaged creative-controller norms on pymetta's lib_deontic for each of the
controller's rules and physixCN's answers, a differential check against an oracle written from the rules' and the
answers' text alone over generated step-requests, the refusal of a norm set lib_deontic would partly skip, and the
wire, CLI and skill surfaces."""

from __future__ import annotations

import json
from datetime import datetime, timezone

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
AT = "2026-11-05T00:00:00Z"
_, NORMS = norms_text({"packaged": "creative-controller"})


# am[related a-gc-step-request-1104]
def _step(target="(target provider claude)", leaves="(h1 image CC-BY-4.0)", cost="(cost 4 10 usd)", facts="(facts)",
          extra=""):
    return f"(step-request {HEAD} {extra} {target} (leaves {leaves}) {cost} {facts})"


# am[related a-gc-step-request-1104]
def _budget():
    return RunBudget(inference_budget=10**10, timeout_seconds=1200)


# am[verifies a-gc-step-request-1104]
def test_a_step_request_gives_each_clause_as_a_fact_and_the_exact_destination():
    text = _step(target="(target pool host-3 trusted)",
                 leaves='(h1 image CC-BY-4.0) ("sha256:ab" audio own (unreleased (private maya)))',
                 cost="(cost 12.5 10 usd)", facts="(facts ((scene-final c1) unverified ev-9))")
    assert step_facts(text).facts == (
        "(op render-job op-17 job-3)", "(generation s1 r1 t1 c1)", "(context task-9 maya studio critic-a blender hq)",
        "(target pool host-3 trusted)", "(sends-to host-3)",
        "(leaf h1 image CC-BY-4.0)", '(leaf "sha256:ab" audio own)', '(unreleased "sha256:ab")',
        '(private "sha256:ab" maya)',
        "(cost 12.5 10 usd)", "(over-budget 12.5 10 usd)",
        "(fact (scene-final c1) unverified ev-9)")


# The answers' shapes: a class nobody knows given as open, sources and from links given as facts, a fact read at the
# request's at, and one whose until is not after it, or that is revoked, left out and reported as absent.
# am[verifies a-gc-ans-pool-open-1104] am[verifies a-gc-ans-derived-tags-1104] am[verifies a-gc-ans-consent-expiry-1104]
def test_the_answers_shapes_give_their_facts_and_report_what_reads_as_absent():
    read = step_facts(_step(
        target="(target pool host-3 partner)", leaves="(h4 render own ((from h1 h2)))",
        facts="(facts ((consent maya h4 host-3) verified ev-1 (until 2026-11-05T00:00:00Z)) "
              "((rights-cleared h1) verified ev-2 (until 2026-11-06T00:00:00Z)) ((scene-final c1) unverified ev-3) "
              "((scene-final c1) revoked ev-4))",
        extra=f"(at {AT}) (sources (h1 photo own ((private maya))) (h2 audio CC0 (unreleased)))"))
    assert read.at == datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert read.facts[3:] == (
        "(target pool host-3 open)", "(sends-to host-3)",
        "(leaf h4 render own)", "(from h4 h1)", "(from h4 h2)",
        "(source h1 photo own)", "(private h1 maya)", "(source h2 audio CC0)", "(unreleased h2)",
        "(cost 4 10 usd)", "(fact (rights-cleared h1) verified ev-2)")
    assert read.absent == (("(consent maya h4 host-3)", "ev-1", "expired"), ("(scene-final c1)", "ev-3", "revoked"),
                           ("(scene-final c1)", "ev-4", "revoked"))
    moment = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert step_facts(_step(), now=moment).at == moment
    assert step_facts(_step(extra=f"(at {AT})"), now=moment).at == datetime(2026, 11, 5, tzinfo=timezone.utc)


# am[verifies a-gc-step-request-1104]
def test_a_cost_at_the_budget_left_is_not_over_it():
    assert "(over-budget 10 10 usd)" not in step_facts(_step(cost="(cost 10 10 usd)")).facts
    assert "(over-budget 10.5 10 usd)" in step_facts(_step(cost="(cost 10.5 10 usd)")).facts


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
    "a pool target of four items": _step(target="(target pool host-3 trusted extra)"),
    "a provider with a class": _step(target="(target provider claude trusted)"),
    "a leaf of two items": _step(leaves="(h1 image)"),
    "a leaf named twice": _step(leaves="(h1 image MIT) (h1 audio MIT)"),
    "a leaf named again as a source": _step(leaves="(h1 image MIT)", extra="(sources (h1 photo own))"),
    "a tag it doesn't know": _step(leaves="(h1 image MIT (draft))"),
    "tags that aren't a list": _step(leaves="(h1 image MIT unreleased)"),
    "a from naming nothing": _step(leaves="(h1 image MIT ((from)))"),
    "a from naming an asset no one describes": _step(leaves="(h1 image MIT ((from h9)))"),
    "an asset made from itself": _step(leaves="(h1 image MIT ((from h1)))"),
    "a cycle through a source": _step(leaves="(h1 image MIT ((from s1)))", extra="(sources (s1 photo own ((from h1))))"),
    "a source of two items": _step(extra="(sources (s1 photo))"),
    "a fact of another status": _step(facts="(facts ((x) maybe ev-1))"),
    "a fact's fourth item that isn't until": _step(facts="(facts ((x) verified ev-1 (after 2026-11-05T00:00:00Z)))"),
    "an until that isn't a time": _step(facts="(facts ((x) verified ev-1 (until tomorrow)))"),
    "an until without its offset": _step(facts="(facts ((x) verified ev-1 (until 2026-11-05T00:00:00)))"),
    "an until in another zone": _step(facts="(facts ((x) verified ev-1 (until 2026-11-06T00:00:00+11:00)))"),
    "an until to a fraction of a second": _step(facts="(facts ((x) verified ev-1 (until 2026-11-05T00:00:00.5Z)))"),
    "an at with unpadded fields": _step(extra="(at 2026-11-5T0:00:00Z)"),
    "an at of two items": _step(extra=f"(at {AT} {AT})"),
    "an at that isn't a time": _step(extra="(at now)"),
    "a relicence of three items": _step(leaves="(h3 photo own)", facts="(facts ((relicence h3 MIT) verified ev-1))"),
    "a relicence of an asset no one describes": _step(
        facts="(facts ((relicence h9 MIT maya 2026-11-04T00:00:00Z) verified ev-1))"),
    "a relicence of an asset that isn't own": _step(
        leaves="(h1 image MIT)", facts="(facts ((relicence h1 CC0 maya 2026-11-04T00:00:00Z) verified ev-1))"),
    "a relicence whose time isn't one": _step(
        leaves="(h3 photo own)", facts="(facts ((relicence h3 MIT maya yesterday) verified ev-1))"),
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
    "a pool class nobody knows is open": (
        _step(target="(target pool host-3 partner)", leaves="(h2 audio CC-BY-NC-4.0)"),
        "(verdict forbidden ((licence-restricted (send h2 open-host))) ())"),
    "a plain CC name reads as its SPDX version": (
        _step(leaves="(h1 image CC-BY)"),
        "(verdict permitted ((licence-open (send h1 outside-model)) "
        "(attribution-travels (attribution h1 CC-BY-4.0))) ())"),
    "a plain name SPDX doesn't list is restricted": (
        _step(leaves="(h1 code BSD)"),
        "(verdict forbidden ((licence-restricted (send h1 outside-model))) ())"),
    "what is made from unreleased work is unreleased": (
        _step(leaves="(h4 render CC-BY-4.0 ((from h1)))", extra="(sources (h1 photo own (unreleased)))"),
        "(verdict forbidden ((unreleased-trusted-only (send h4 outside-model))) ())"),
    "what is made from private material is private through every step back": (
        _step(leaves="(h5 cut own ((from h4)))", extra="(sources (h4 render own ((from h1))) (h1 photo own ((private maya))))"),
        "(verdict obligated ((private-needs-consent (consent maya h5 claude))) ())"),
    "a private source that stays home needs no consent": (
        _step(extra="(sources (h9 photo own ((private maya))))"),
        "(verdict permitted ((licence-open (send h1 outside-model)) "
        "(attribution-travels (attribution h1 CC-BY-4.0))) ())"),
    "consent past its expiry reads as absent": (
        _step(leaves="(h3 photo own ((private maya)))", extra=f"(at {AT})",
              facts="(facts ((consent maya h3 claude) verified ev-1 (until 2026-11-01T00:00:00Z)))"),
        "(verdict obligated ((private-needs-consent (consent maya h3 claude))) ())"),
    "consent before its expiry lets it go": (
        _step(leaves="(h3 photo own ((private maya)))", extra=f"(at {AT})",
              facts="(facts ((consent maya h3 claude) verified ev-1 (until 2027-01-01T00:00:00Z)))"),
        "(verdict permitted ((licence-open (send h3 outside-model)) (consent-shown (consented maya h3 claude))) (ev-1))"),
    "revoked consent reads as absent": (
        _step(leaves="(h3 photo own ((private maya)))",
              facts="(facts ((consent maya h3 claude) verified ev-1) ((consent maya h3 claude) revoked ev-2))"),
        "(verdict obligated ((private-needs-consent (consent maya h3 claude))) ())"),
    "what is made from non-commercial work is restricted, own never loosening it": (
        _step(leaves="(h4 render own ((from h1)))", extra="(sources (h1 clip CC-BY-NC-4.0))"),
        "(verdict forbidden ((licence-restricted (send h4 outside-model))) ())"),
    "what is made from restricted work may still go to a trusted host": (
        _step(target="(target pool host-3 trusted)", leaves="(h4 render own ((from h1)))",
              extra="(sources (h1 clip proprietary))"),
        "(verdict permitted ((licence-restricted-trusted (send h4 trusted-host))) ())"),
    "what is made from no-derivatives work is restricted": (
        _step(leaves="(h4 render CC-BY-4.0 ((from h1)))", extra="(sources (h1 clip CC-BY-ND-4.0))"),
        "(verdict forbidden ((licence-restricted (send h4 outside-model))) ())"),
    "what is made from share-alike work is shared alike, its source credited": (
        _step(leaves="(h4 render own ((from h1)))", extra="(sources (h1 clip CC-BY-SA-3.0))"),
        "(verdict permitted ((licence-open (send h4 outside-model)) "
        "(source-credit-travels (attribution-from h4 h1 CC-BY-SA-3.0)) (share-alike-travels (share-alike h4 cc-by-sa))) ())"),
    "share-alike versions that combine stay open": (
        _step(leaves="(h4 render CC-BY-SA-4.0 ((from h1)))", extra="(sources (h1 clip CC-BY-SA-2.0))"),
        "(verdict permitted ((licence-open (send h4 outside-model)) "
        "(attribution-travels (attribution h4 CC-BY-SA-4.0)) (source-credit-travels (attribution-from h4 h1 CC-BY-SA-2.0)) "
        "(share-alike-travels (share-alike h4 cc-by-sa))) ())"),
    "share-alike families that can't combine read as restricted": (
        _step(leaves="(h4 render own ((from h1 h2)))", extra="(sources (h1 clip CC-BY-SA-1.0) (h2 clip CC-BY-SA-4.0))"),
        "(verdict forbidden ((licence-restricted (send h4 outside-model))) ())"),
    "a source's credit travels through every step back": (
        _step(leaves="(h5 cut own ((from h4)))", extra="(sources (h4 render own ((from h1))) (h1 clip CC-BY-4.0))"),
        "(verdict permitted ((licence-open (send h5 outside-model)) "
        "(source-credit-travels (attribution-from h5 h1 CC-BY-4.0))) ())"),
    "a verified relicence gives an own asset its new licence": (
        _step(leaves="(h4 render own)", facts="(facts ((relicence h4 CC-BY maya 2026-11-04T09:00:00Z) verified ev-7))"),
        "(verdict permitted ((licence-open (send h4 outside-model)) "
        "(attribution-travels (attribution h4 CC-BY-4.0))) (ev-7))"),
    "a relicence by its SPDX id gives that licence": (
        _step(leaves="(h4 render own)", facts="(facts ((relicence h4 MIT maya 2026-11-04T09:00:00Z) verified ev-7))"),
        "(verdict permitted ((licence-open (send h4 outside-model))) (ev-7))"),
    "a relicence can restrict": (
        _step(leaves="(h4 render own)",
              facts="(facts ((relicence h4 CC-BY-NC-4.0 maya 2026-11-04T09:00:00Z) verified ev-7))"),
        "(verdict forbidden ((licence-restricted (send h4 outside-model))) ())"),
    "a relicence keeps what the asset was made from binding it": (
        _step(leaves="(h4 render own ((from h1)))", extra="(sources (h1 clip CC-BY-NC-4.0))",
              facts="(facts ((relicence h4 CC-BY-4.0 maya 2026-11-04T09:00:00Z) verified ev-7))"),
        "(verdict forbidden ((licence-restricted (send h4 outside-model))) ())"),
    "an unverified relicence is verified first and changes nothing yet": (
        _step(leaves="(h4 render own)",
              facts="(facts ((relicence h4 CC-BY-NC-4.0 maya 2026-11-04T09:00:00Z) unverified ev-7))"),
        "(verdict obligated ((verify-first (verify (relicence h4 CC-BY-NC-4.0 maya 2026-11-04T09:00:00Z)))) (ev-7))"),
}


# am[verifies a-gc-step-request-1104]
@pytest.mark.parametrize("case", sorted(VERDICTS))
def test_each_rule_gives_the_verdict_the_controller_reads(case):
    text, expected = VERDICTS[case]
    assert verdict(text, NORMS, budget=_budget()).atom() == expected


# The oracle reads the controller's rules as physixCN wrote them (omegahive#11, comment 6607935015) and their answers
# (comments 6628012601 and 6653935601), and nothing of the norm set: where a step's leaves may go, what waits for consent
# or verification, and what the budget forbids. Licences are SPDX ids or own, plain CC names their current SPDX
# versions; what an asset is made from binds it with every restriction, share-alike family and credit it carries, two
# share-alike families that can't combine making it restricted; a verified relicence replaces an own licence.
OPEN = {"own", "CC0-1.0", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause",
        *(f"CC-BY{sa}-{version}" for sa in ("", "-SA") for version in ("1.0", "2.0", "2.5", "3.0", "4.0"))}
CREDIT = {f"CC-BY{sa}-{version}" for sa in ("", "-SA") for version in ("1.0", "2.0", "2.5", "3.0", "4.0")}
# CC BY-SA 2.0 and later admit later versions for adaptations, 1.0 only itself (their legal codes, section 4(b)).
FAMILY = {f"CC-BY{nc}-SA-{v}": f"cc-by{nc.lower()}-sa{'-1' if v == '1.0' else ''}"
          for nc in ("", "-NC") for v in ("1.0", "2.0", "2.5", "3.0", "4.0")}
ALIASES = {"CC0": "CC0-1.0", **{f"CC-BY{kind}": f"CC-BY{kind}-4.0" for kind in ("", "-SA", "-NC", "-ND", "-NC-SA",
                                                                             "-NC-ND")}}
LICENCES = ["own", "CC0-1.0", "CC0", "CC-BY-4.0", "CC-BY", "CC-BY-SA-3.0", "CC-BY-SA", "MIT", "Apache-2.0",
            "BSD-3-Clause", "BSD", "CC-BY-NC-4.0", "CC-BY-NC", "CC-BY-ND-4.0", "CC-BY-NC-SA-4.0", "proprietary",
            "unknown"]
SOURCE_LICENCES = ["own", "own", "CC-BY-4.0", "CC-BY-SA-1.0", "CC-BY-SA-3.0", "CC-BY-SA", "CC-BY-NC-4.0",
                   "CC-BY-ND-4.0", "MIT"]
# What a relicence may name: no share-alike licence, so no literal a relicence supports has a second derivation the
# engine might report in its place.
RELICENCES = ["CC-BY", "CC-BY-4.0", "MIT", "CC-BY-NC-4.0", "proprietary"]
RELICENSED_AT = "2026-11-04T09:00:00Z"
DESTINATIONS = {("provider", None): "outside-model", ("pool", "own"): "own-machine",
                ("pool", "trusted"): "trusted-host", ("pool", "open"): "open-host", ("pool", None): "open-host",
                ("pool", "partner"): "open-host"}
UNTIL = {"none": None, "past": "2026-11-01T00:00:00Z", "future": "2027-01-01T00:00:00Z"}


# Each asset's licence as the request leaves it, and the ref of the relicence it came from, if any.
# am[related a-gc-lic-tests-1105]
def _licence(name, stated, present):
    licence = ALIASES.get(stated, stated)
    if stated == "own":
        for fact, status, ref in present:
            if status == "verified" and fact.startswith(f"(relicence {name} "):
                new = fact.split()[2]
                return ALIASES.get(new, new), ref
    return licence, None


# am[related a-gc-step-request-1104] am[rests-on c-gc-step-rules-1104]
# am[rests-on c-gc-physix-answers-1104] am[rests-on c-gc-physix-licence-1105] am[rests-on c-gc-by-sa-versions-1105]
def _oracle(kind, cls, where, leaves, assets, estimate, left, facts):
    """(status, {literal: rules that may name it}, evidence refs) for a step, from the rules' text: each leaf is
    (name, licence, unreleased, owners), its tags already those of everything it came from, `assets` maps every
    asset's name to (stated licence, the names it came from), and each fact is (fact, status, ref, until)."""
    destination = DESTINATIONS[(kind, cls)]
    untrusted = destination in ("outside-model", "open-host")
    revoked = {fact for fact, status, _, _ in facts if status == "revoked"}
    present = [(fact, status, ref) for fact, status, ref, until in facts
               if fact not in revoked and (until is None or until > AT)]
    licences = {name: _licence(name, stated, present) for name, (stated, _) in assets.items()}

    def ancestors(name):
        seen, todo = [], list(assets[name][1])
        while todo:
            origin = todo.pop()
            if origin not in seen:
                seen.append(origin)
                todo += assets[origin][1]
        return seen

    def restricted(name):
        lineage = [name, *ancestors(name)]
        families = {FAMILY[licences[a][0]] for a in lineage if licences[a][0] in FAMILY}
        return len(families) > 1 or any(licences[a][0] not in OPEN for a in lineage)

    forbidden, obligated, permitted, evidence = {}, {}, {}, {"obligated": [], "permitted": []}
    for name, _, unreleased, owners in leaves:
        send = f"(send {name} {destination})"
        licence, relicence = licences[name]
        bound = restricted(name)
        rules = {*(["licence-restricted"] if bound and untrusted else []),
                 *(["unreleased-trusted-only"] if unreleased and untrusted else [])}
        if rules:
            forbidden[send] = rules
        else:
            permitted[send] = {"licence-restricted-trusted" if bound else "licence-open"}
            if not bound and relicence:
                evidence["permitted"].append(relicence)
        if licence in CREDIT:
            permitted[f"(attribution {name} {licence})"] = {"attribution-travels"}
            if relicence:
                evidence["permitted"].append(relicence)
        for origin in ancestors(name):
            if licences[origin][0] in CREDIT:
                permitted[f"(attribution-from {name} {origin} {licences[origin][0]})"] = {"source-credit-travels"}
        for family in sorted({FAMILY[licences[a][0]] for a in [name, *ancestors(name)] if licences[a][0] in FAMILY}):
            permitted[f"(share-alike {name} {family})"] = {"share-alike-travels"}
        for owner in sorted(owners) if destination != "own-machine" else ():
            consent = f"(consent {owner} {name} {where})"
            ref = next((r for fact, status, r in present if fact == consent and status == "verified"), None)
            if ref is None:
                obligated[consent] = {"private-needs-consent"}
            else:
                permitted[f"(consented {owner} {name} {where})"] = {"consent-shown"}
                evidence["permitted"].append(ref)
    if estimate > left:
        forbidden[f"(auto-dispatch {estimate} {left} usd)"] = {"budget-over-left"}
    for fact, status, ref in present:
        if status == "unverified":
            obligated[f"(verify {fact})"] = {"verify-first"}
            evidence["obligated"].append(ref)
    if forbidden:
        return "forbidden", forbidden, []
    if obligated:
        return "obligated", obligated, evidence["obligated"]
    return "permitted", permitted, evidence["permitted"]


# Assets as (licence, unreleased, owner, the indexes of the sources it came from), sources only from earlier sources,
# so no request has a cycle.
_owner = st.sampled_from([None, "maya", "ola"])
_leaves = st.lists(st.tuples(st.sampled_from(LICENCES), st.booleans(), _owner, st.sets(st.integers(0, 1))),
                   max_size=3)
_sources = st.lists(st.tuples(st.sampled_from(SOURCE_LICENCES), st.booleans(), _owner, st.sets(st.integers(0, 1))),
                    max_size=2)
# One fact per name: a fact given twice is one literal the engine supports with one of its refs; the rule table holds
# a revocation beside the fact it revokes. A relicence names an own leaf, if the step has one.
_facts = st.lists(st.tuples(st.sampled_from(["(scene-final c1)", "(rights-cleared a0)", "consent", "relicence"]),
                            st.sampled_from(["verified", "unverified", "revoked"]), st.sampled_from(sorted(UNTIL))),
                  max_size=3, unique_by=lambda fact: fact[0])
_relicences = st.sampled_from(RELICENCES)


# am[related a-gc-ans-derived-tags-1104]
def _asset_text(name, licence, unreleased, owner, origins):
    tags = [*(["unreleased"] if unreleased else []), *([f"(private {owner})"] if owner else []),
            *([f"(from {' '.join(origins)})"] if origins else [])]
    return f"({name} image {licence}{' (' + ' '.join(tags) + ')' if tags else ''})"


# am[verifies a-gc-step-request-1104] am[verifies a-gc-ans-pool-open-1104] am[verifies a-gc-ans-spdx-1104]
# am[verifies a-gc-ans-consent-expiry-1104] am[verifies a-gc-ans-derived-tags-1104] am[verifies a-gc-lic-norms-1105]
# am[verifies a-gc-lic-reader-1105]
@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(target=st.sampled_from(sorted(DESTINATIONS, key=str)), leaves=_leaves, sources=_sources,
       estimate=st.sampled_from([0, 4, 10, 12]), facts=_facts, consent_for=st.sampled_from(["claude", "host-3"]),
       relicence_to=_relicences)
def test_the_norms_agree_with_the_rules_as_written(target, leaves, sources, estimate, facts, consent_for, relicence_to):
    kind, cls = target
    where = "claude" if kind == "provider" else "host-3"
    # Each source's tags with everything it came from, earlier sources only; then each leaf's alike.
    inherited = []
    for i, (_, unreleased, owner, origins) in enumerate(sources):
        origins = sorted(j for j in origins if j < i)
        tags = (unreleased or any(inherited[j][0] for j in origins),
                {owner} - {None} | {person for j in origins for person in inherited[j][1]})
        inherited.append((*tags, origins, unreleased, owner))
    named = []
    for i, (licence, unreleased, owner, origins) in enumerate(leaves):
        origins = sorted(j for j in origins if j < len(sources))
        named.append((f"a{i}", licence, unreleased or any(inherited[j][0] for j in origins),
                      {owner} - {None} | {person for j in origins for person in inherited[j][1]}, origins,
                      unreleased, owner))
    owners = [(name, owner) for name, _, _, everyone, *_ in named for owner in sorted(everyone)]
    own_leaves = [name for name, licence, *_ in named if licence == "own"]
    written = []
    for i, (fact, status, until) in enumerate(facts):
        if fact == "consent":
            if not owners:
                continue
            name, owner = owners[i % len(owners)]
            fact = f"(consent {owner} {name} {consent_for})"
        elif fact == "relicence":
            if not own_leaves:
                continue
            fact = f"(relicence {own_leaves[i % len(own_leaves)]} {relicence_to} maya {RELICENSED_AT})"
        written.append((fact, status, f"ev-{i}", UNTIL[until]))
    target_text = f"(target {kind} {where}{'' if cls is None else ' ' + cls})"
    leaf_text = " ".join(_asset_text(name, licence, unreleased, owner, [f"s{j}" for j in origins])
                         for name, licence, _, _, origins, unreleased, owner in named)
    source_text = " ".join(_asset_text(f"s{i}", sources[i][0], unreleased, owner, [f"s{j}" for j in origins])
                           for i, (_, _, origins, unreleased, owner) in enumerate(inherited))
    assets = {**{f"s{i}": (sources[i][0], [f"s{j}" for j in origins]) for i, (_, _, origins, _, _) in enumerate(inherited)},
              **{name: (licence, [f"s{j}" for j in origins]) for name, licence, _, _, origins, _, _ in named}}
    fact_text = " ".join(f"({fact} {status} {ref}{'' if until is None else f' (until {until})'})"
                         for fact, status, ref, until in written)
    text = _step(target=target_text, leaves=leaf_text, cost=f"(cost {estimate} 10 usd)", facts=f"(facts {fact_text})",
                 extra=f"(at {AT})" + (f" (sources {source_text})" if sources else ""))
    status, reasons, evidence = _oracle(kind, cls, where, [leaf[:4] for leaf in named], assets, estimate, 10, written)
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
    answer = run_step_request({"step_request": _step(extra=f"(at {AT})"), "norms": {"packaged": "creative-controller"}},
                              budget=_budget())
    assert answer["protocol"] == "goalchainer-step-request-v1" and answer["norms"] == "creative-controller"
    assert answer["verdict"] == VERDICTS["an open asset goes anywhere, its attribution with it"][1]
    assert answer["authorization"] == "unresolved" and answer["applies_effects"] is False
    assert answer["reasons"][0] == {"rule": "licence-open", "literal": "(send h1 outside-model)"}
    assert answer["inferences"] > 0 and answer["support"][0]["label"] == "licence-open"
    assert answer["at"] == AT and answer["absent"] == []
    revoked = run_step_request({"step_request": _step(facts="(facts ((scene-final c1) revoked ev-4))"),
                                "norms": {"packaged": "creative-controller"}}, budget=_budget())
    assert revoked["absent"] == [{"fact": "(scene-final c1)", "ref": "ev-4", "why": "revoked"}]
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
