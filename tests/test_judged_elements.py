"""Purpose: test GoalChainer's judged reading of a request's elements: the semrewrite judge command's contract and each
failure it must refuse, each element taking its best statement, the opinion's evidence reading back as the opinion in
SNARS, the session believing the judge in place of the policy's keyword assertion, and, natively with a fake judge,
that the decision reads the judge and not the keywords; one test runs the real semrewrite judge when it is reachable."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from goal_chainer import judged_elements as je
from goal_chainer.judged_elements import (
    BASE_RATES,
    ELEMENTS,
    SOURCE,
    STATEMENTS,
    TRUST,
    ElementOpinion,
    believe_elements,
    judged_elements,
    read_request_elements,
    selected_reading,
)
from goal_chainer.pipeline import decide_incident
from goal_chainer.snars_decision import native_decision_payload
from goal_chainer.snars_models import (
    SnarsDependencyUnavailableError,
    SnarsInvalidInputError,
    SnarsPersistenceError,
    SnarsProtocolError,
    SnarsTimeoutError,
    SubjectiveOpinion,
)
from goal_chainer.snars_program import SnarsProgramBuilder
from goal_chainer.snars_reasoner import SnarsSession
from goal_chainer.snars_runtime import REPO_ROOT

FAKE_COMMAND = shlex.join([sys.executable, str(Path(__file__).parent / "fixtures" / "fake_semrewrite.py")])
REQUEST = "The logs contain public information and are safe to publish. Engineering needs the incident room."
EMAILS = "The data includes customer emails."
COMMIT = "c" * 40
STATEMENT = '(sn p so "is" ((arg s (sn c "a")) (arg o (sn c "b"))))'


# am[verifies a-gcje-runner]
def _rows(pairs, beliefs, *, trust=TRUST, base_rate=0.5):
    """What semrewrite judge writes for `pairs`: the belief and disbelief `beliefs` gives each conclusion, discounted
    by the trust and rounded to six decimals."""
    rows = []
    for premise, conclusion in pairs:
        b, d = (trust * x for x in beliefs.get(conclusion, (0.0, 0.0)))
        rows.append({"premise": premise, "conclusion": conclusion, "belief": round(b, 6), "disbelief": round(d, 6),
                     "uncertainty": round(1 - b - d, 6), "base_rate": base_rate})
    return rows


# am[verifies a-gcje-runner]
def _fake_judge(monkeypatch, beliefs=None, failure=None):
    monkeypatch.setenv("GOALCHAINER_SEMREWRITE", FAKE_COMMAND)
    monkeypatch.setenv("FAKE_JUDGE_BELIEFS", json.dumps(beliefs or {}))
    if failure is None:
        monkeypatch.delenv("FAKE_JUDGE_FAIL", raising=False)
    else:
        monkeypatch.setenv("FAKE_JUDGE_FAIL", failure)


# am[verifies a-gcje-runner]
def test_reading_defaults_to_keywords_and_refuses_other_values(monkeypatch) -> None:
    monkeypatch.delenv("GOALCHAINER_ELEMENTS", raising=False)
    assert selected_reading() == "keywords"
    monkeypatch.setenv("GOALCHAINER_ELEMENTS", " Judged ")
    assert selected_reading() == "judged"
    monkeypatch.setenv("GOALCHAINER_ELEMENTS", "cosine")
    with pytest.raises(SnarsInvalidInputError, match="keywords or judged"):
        selected_reading()


# am[verifies a-gcje-statements]
def test_each_element_takes_its_best_statement_at_its_base_rate() -> None:
    weak, strong = STATEMENTS["sensitive-data"][0], STATEMENTS["sensitive-data"][-1]
    opinions = judged_elements("anything", run=lambda pairs: _rows(pairs, {weak: (0.3, 0.0), strong: (0.9, 0.05)}))

    sensitive = opinions["sensitive-data"]
    assert sensitive.statement == strong
    assert sensitive.opinion.base_rate == BASE_RATES["sensitive-data"]
    assert sensitive.opinion.belief == pytest.approx(TRUST * 0.9, abs=1e-6)
    assert sensitive.opinion.expectation == pytest.approx(
        TRUST * 0.9 + BASE_RATES["sensitive-data"] * (1 - TRUST * 0.95), abs=1e-6)
    # Elements the judge says nothing about keep their first statement, vacuous, at their own base rate.
    for element in ELEMENTS[1:]:
        assert opinions[element].statement == STATEMENTS[element][0]
        assert opinions[element].evidence is None
        assert opinions[element].opinion.expectation == pytest.approx(BASE_RATES[element])


# am[verifies a-gcje-believe]
@given(st.floats(0.0, 1.0), st.floats(0.0, 1.0), st.floats(0.01, 0.99))
def test_evidence_reads_back_as_the_opinion_in_snars(belief, share, base_rate) -> None:
    # Any opinion the judge's trust allows: belief and disbelief together at most TRUST.
    b = TRUST * belief * share
    d = TRUST * belief * (1 - share)
    opinion = ElementOpinion("unverified", STATEMENTS["unverified"][0], SubjectiveOpinion(b, d, 1 - b - d, base_rate))
    evidence = opinion.evidence
    if b == 0.0 and d == 0.0:
        assert evidence is None
        return
    assert evidence is not None
    # SNARS's sn opinion: (r, s) at base rate a is (r/t, s/t, 2/t, a) with t = r + s + 2.
    total = evidence.positive + evidence.negative + 2.0
    assert evidence.positive / total == pytest.approx(b, abs=1e-12)
    assert evidence.negative / total == pytest.approx(d, abs=1e-12)
    assert 2.0 / total == pytest.approx(1 - b - d, abs=1e-12)
    assert evidence.base_rate == base_rate


# am[verifies a-gcje-believe]
def test_a_dogmatic_opinion_has_no_evidence_to_believe() -> None:
    with pytest.raises(SnarsProtocolError, match="dogmatic"):
        ElementOpinion("public-data", STATEMENTS["public-data"][0], SubjectiveOpinion(1.0, 0.0, 0.0, 0.5))
    with pytest.raises(SnarsInvalidInputError, match="one of its statements"):
        ElementOpinion("public-data", EMAILS, SubjectiveOpinion(0.5, 0.0, 0.5, 0.5))


# am[verifies a-gcje-runner]
def _broken(change):
    def run(pairs):
        rows = _rows(pairs, {EMAILS: (0.9, 0.0)})
        return change(rows)

    return run


# am[verifies a-gcje-runner]
def _set(field, value):
    def change(rows):
        rows[0][field] = value
        return rows

    return change


# am[verifies a-gcje-runner]
@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda rows: rows[:-1], "different number"),
        (lambda rows: ["not an object", *rows[1:]], "not a JSON object"),
        (_set("premise", "another request"), "different pair"),
        (_set("conclusion", "another statement"), "different pair"),
        (_set("belief", "0.5"), "no belief"),
        (_set("belief", True), "no belief"),
        (_set("disbelief", 1.5), "no disbelief"),
        (_set("uncertainty", 0.5), "sum to one"),
        (_set("base_rate", 0.4), "base rate"),
        (lambda rows: [{**rows[0], "belief": 0.99, "uncertainty": 0.01}, *rows[1:]], "discounted"),
    ],
)
def test_judge_rows_breaking_the_contract_are_refused(change, message) -> None:
    with pytest.raises(SnarsProtocolError, match=message):
        judged_elements("anything", run=_broken(change))


# am[verifies a-gcje-runner]
def test_the_judge_command_runs_the_deployed_judge(monkeypatch) -> None:
    _fake_judge(monkeypatch, {EMAILS: (0.95, 0.0)})

    opinions = judged_elements(REQUEST)

    assert opinions["sensitive-data"].statement == EMAILS
    assert opinions["sensitive-data"].opinion.expectation > 0.5
    assert all(opinions[e].evidence is None for e in ELEMENTS[1:])


# am[verifies a-gcje-runner]
def test_a_missing_judge_command_is_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GOALCHAINER_SEMREWRITE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SnarsDependencyUnavailableError, match="unavailable") as missing:
        judged_elements(REQUEST)
    assert "GOALCHAINER_SEMREWRITE" in str(missing.value.details["remedy"])

    monkeypatch.setenv("GOALCHAINER_SEMREWRITE", str(tmp_path / "semrewrite"))
    with pytest.raises(SnarsDependencyUnavailableError, match="cannot be started"):
        judged_elements(REQUEST)

    monkeypatch.setenv("GOALCHAINER_SEMREWRITE", 'python "unclosed')
    with pytest.raises(SnarsInvalidInputError, match="not a command line"):
        judged_elements(REQUEST)


# am[verifies a-gcje-runner]
def test_a_failing_judge_command_is_a_structured_error(monkeypatch) -> None:
    _fake_judge(monkeypatch, failure="exit")
    with pytest.raises(SnarsDependencyUnavailableError, match="judge failed") as failed:
        judged_elements(REQUEST)
    assert failed.value.details["returncode"] == 3
    assert "fake judge nli-deberta-large refused" in str(failed.value.details["stderr"])

    _fake_judge(monkeypatch, failure="garbage")
    with pytest.raises(SnarsProtocolError, match="not JSON"):
        judged_elements(REQUEST)

    _fake_judge(monkeypatch, failure="sleep")
    with pytest.raises(SnarsTimeoutError, match="in time"):
        judged_elements(REQUEST, timeout=0.5)


# am[verifies a-gcje-believe]
class _BelievingSession:
    """The parts of a SNARS session believe_elements uses, recording each belief."""

    def __init__(self, requests=("the request",), *, assert_request_context=False) -> None:
        self.assert_request_context = assert_request_context
        self.builder = SnarsProgramBuilder(_runtime())
        self.store = SimpleNamespace(events=lambda: tuple(
            SimpleNamespace(kind="ingest_text", payload={"text": text}) for text in requests))
        self.beliefs = []

    def believe(self, statement, *, evidence, source):
        self.beliefs.append((statement, evidence, source))
        return statement


# am[verifies a-gcje-believe]
def _fake(double: object) -> Any:
    """A test double passed where the real session or runtime is expected, which it imitates in the parts used."""
    return double


# am[verifies a-gcje-believe]
def _runtime() -> Any:
    return SimpleNamespace(
        diagnostics=SimpleNamespace(mettabase_dir=REPO_ROOT / "external" / "mettabase", mettabase_commit=COMMIT),
        timeout_seconds=5.0,
    )


# am[verifies a-gcje-believe]
def test_believing_skips_vacuous_elements_and_names_the_judge() -> None:
    session: Any = _BelievingSession()
    opinions = judged_elements("anything", run=lambda pairs: _rows(pairs, {EMAILS: (0.9, 0.05)}))

    beliefs = believe_elements(session, opinions)

    assert list(beliefs) == ["sensitive-data"]
    ((statement, evidence, source),) = session.beliefs
    assert statement == '(sn p so "has-property" ((arg s (sn c "request")) (arg o (sn c "sensitive-data"))))'
    assert source == SOURCE == "semrewrite:nli-deberta-large"
    assert evidence == opinions["sensitive-data"].evidence


# am[verifies a-gcje-believe]
def test_believing_refuses_a_store_holding_another_request() -> None:
    opinions = judged_elements("anything", run=lambda pairs: _rows(pairs, {EMAILS: (0.9, 0.0)}))
    with pytest.raises(SnarsPersistenceError, match="one request per SNARS store"):
        believe_elements(_fake(_BelievingSession(("first request", "second request"))), opinions)
    with pytest.raises(SnarsInvalidInputError, match="one opinion for each element"):
        believe_elements(_fake(_BelievingSession()), {"sensitive-data": opinions["sensitive-data"]})


# am[verifies a-goalchainer-judged-elements.judged-path]
def test_reading_request_elements_follows_the_reading(monkeypatch) -> None:
    _fake_judge(monkeypatch, {EMAILS: (0.95, 0.0)})
    keywords = _BelievingSession(assert_request_context=True)
    assert read_request_elements(_fake(keywords), REQUEST, "keywords") is None
    assert keywords.beliefs == []
    with pytest.raises(SnarsInvalidInputError, match="leaves the keyword assertion out"):
        read_request_elements(_fake(keywords), REQUEST, "judged")

    judged = _BelievingSession()
    opinions = read_request_elements(_fake(judged), REQUEST, "judged")

    assert opinions is not None and opinions["sensitive-data"].statement == EMAILS
    assert [source for _, _, source in judged.beliefs] == [SOURCE]


# am[verifies a-gcje-believe]
def _effects(program: str) -> str:
    """The batch's last line, the query whose let* binds every effect; the policy text above it also defines
    gc assert-request-context!, so only this line says whether the batch runs it."""
    return program.rstrip().splitlines()[-1]


# am[verifies a-gcje-believe]
def test_the_policy_batch_omits_the_keyword_assertion_only_when_asked() -> None:
    builder = SnarsProgramBuilder(_runtime())
    operation = builder.codec.expression("gc", builder.codec.symbol("context-record"))

    keywords = builder.batch(operation, include_policy=True)
    judged = builder.batch(operation, include_policy=True, assert_request_context=False)

    assert "(gc assert-request-context!)" in _effects(keywords)
    assert "(gc assert-request-context!)" not in _effects(judged)
    assert "(gc init-policy!)" in _effects(judged) and "(sn cycles 2)" in _effects(judged)


# am[verifies a-gcje-believe]
class _RecordingRuntime:
    """A runtime answering every batch with one belief record and keeping the programs it ran."""

    def __init__(self) -> None:
        self.diagnostics = _runtime().diagnostics
        self.programs: list[str] = []

    def run_batch(self, program: str):
        self.programs.append(program)
        return SimpleNamespace(output_lines=(
            f"""(goalchainer-snars-v1 belief ok
                  (belief sid-1 {STATEMENT} (opinion 0.6 0.1 0.3 0.5) (evidence 6 1 0.5)
                    (receipts ((receipt receipt-1 "caller" sid-1 1.0))) (proofs ()) (occurrences ())))""",
        ))


# am[verifies a-gcje-believe]
def test_the_session_flag_reaches_its_batches_and_an_identical_belief_is_recorded_once() -> None:
    runtime = _RecordingRuntime()
    with SnarsSession.ephemeral(_fake(runtime), assert_request_context=False) as session:
        session.believe(STATEMENT, source="caller")
        session.believe(STATEMENT, source="caller")
        assert [event.kind for event in session.store.events()] == ["belief"]
    assert all("(gc init-policy!)" in _effects(p) and "(gc assert-request-context!)" not in _effects(p)
               for p in runtime.programs)
    # The repeat replays the stored belief and adds no second believe! effect.
    assert _effects(runtime.programs[1]).count("(believe!") == 1


# am[verifies a-goalchainer-judged-elements.judged-path]
def test_offline_mode_refuses_judged_elements(monkeypatch) -> None:
    monkeypatch.setenv("GOALCHAINER_ELEMENTS", "judged")
    with pytest.raises(SnarsInvalidInputError, match="only in native mode"):
        decide_incident(REQUEST, mode="offline")


# am[verifies a-goalchainer-judged-elements.judged-path]
def test_native_decision_reads_the_judge_and_not_the_keywords(monkeypatch) -> None:
    # The keywords read this request as public and needing coordination; the judge reads only customer emails.
    monkeypatch.setenv("GOALCHAINER_ELEMENTS", "judged")
    _fake_judge(monkeypatch, {EMAILS: (0.95, 0.0)})

    payload = native_decision_payload(REQUEST)

    context = payload["request_context"]
    expected = payload["elements"]["opinions"]["sensitive-data"]["evidence"]
    assert payload["elements"]["reading"] == "judged"
    assert context["sensitive"]["sources"] == [SOURCE]
    assert context["sensitive"]["evidence"]["positive"] == pytest.approx(expected["positive"], rel=1e-6)
    assert context["sensitive"]["evidence"]["base_rate"] == pytest.approx(BASE_RATES["sensitive-data"])
    for field in ("public", "unverified", "coordination"):
        assert context[field]["evidence"]["positive"] == 0
        assert context[field]["sources"] == []
    assert payload["evidence"]["provenance"] == f"{SOURCE}+mettabase-snars"
    raw = next(row for row in payload["decisions"] if row["action_id"] == "publish_raw_log")
    assert raw["status"] == "blocked"
    assert raw["norm_status"] == "forbidden"


# am[verifies a-gcje-believe]
def test_native_judged_replay_is_structurally_identical(monkeypatch, tmp_path) -> None:
    # A second, different request is refused before the judge reads it: ingest_text's inspection already fails on a
    # store holding two requests in either reading (i-gcje-two-request-store), so the unit test above covers the
    # judged path's own refusal.
    monkeypatch.setenv("GOALCHAINER_ELEMENTS", "judged")
    _fake_judge(monkeypatch, {EMAILS: (0.95, 0.0)})
    database = tmp_path / "judged.sqlite3"

    first, second = (native_decision_payload(REQUEST, store_path=database) for _ in range(2))

    assert first["state"]["digest"] == second["state"]["digest"]
    assert first["state"]["event_count"] == second["state"]["event_count"]
    assert first["decisions"] == second["decisions"]
    assert first["elements"] == second["elements"]


# am[verifies a-goalchainer-judged-elements.judged-path]
def _semrewrite_reachable() -> bool:
    configured = os.environ.get("GOALCHAINER_SEMREWRITE", "")
    return (bool(configured.strip()) and "fake_semrewrite" not in configured) or shutil.which("semrewrite") is not None


# am[verifies a-goalchainer-judged-elements.judged-path]
@pytest.mark.skipif(not _semrewrite_reachable(), reason="semrewrite is not reachable: set GOALCHAINER_SEMREWRITE")
def test_semrewrite_judge_reads_the_brief_request_by_meaning(monkeypatch) -> None:
    monkeypatch.setenv("GOALCHAINER_ELEMENTS", "judged")
    request = "Raw logs include customer emails. Engineering needs the incident room."

    payload = native_decision_payload(request)

    elements = payload["elements"]["opinions"]
    assert elements["sensitive-data"]["opinion"]["expectation"] > 0.5
    assert elements["public-data"]["opinion"]["expectation"] < 0.5
    assert payload["request_context"]["sensitive"]["sources"] == [SOURCE]
    assert payload["decisions"][0]["action_id"] == "publish_redacted_summary"
    assert je.JUDGE in payload["evidence"]["provenance"]
