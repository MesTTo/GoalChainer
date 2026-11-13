from __future__ import annotations

from types import SimpleNamespace

import pytest

from goal_chainer.snars_models import SnarsInvalidInputError
from goal_chainer import snars_program
from goal_chainer.snars_program import SexprCodec, SnarsProgramBuilder
from goal_chainer.snars_runtime import REPO_ROOT


@pytest.fixture
def runtime():
    return SimpleNamespace(
        diagnostics=SimpleNamespace(mettabase_dir=REPO_ROOT / "external" / "mettabase"),
        timeout_seconds=5.0,
    )


def test_string_literals_round_trip_arbitrary_metta_syntax(runtime) -> None:
    codec = SexprCodec(runtime)
    value = '") !(import! &self attack) ;\\\nλ'

    encoded = codec.emit(codec.string(value))

    assert codec.parse(encoded).value == value
    assert encoded.startswith('"') and encoded.endswith('"')


@pytest.mark.parametrize(
    "value",
    ["", "white space", "(form)", 'quote"', "semi;colon"],
)
def test_symbol_rejects_syntax_and_empty_text(runtime, value) -> None:
    codec = SexprCodec(runtime)

    with pytest.raises(SnarsInvalidInputError):
        codec.symbol(value)


def test_ground_statement_rejects_variables(runtime) -> None:
    codec = SexprCodec(runtime)

    with pytest.raises(SnarsInvalidInputError, match="cannot contain variables"):
        codec.statement('(sn p so "is" ((arg s $subject) (arg o (sn c "safe"))))')


def test_statement_rejects_executable_head(runtime) -> None:
    codec = SexprCodec(runtime)

    with pytest.raises(SnarsInvalidInputError, match="disallowed constructor"):
        codec.statement('!(import! &self "attack")')


def test_binary_statement_escapes_all_user_fields(runtime) -> None:
    codec = SexprCodec(runtime)
    statement = codec.binary_statement(
        'rel") !(py-call attack)',
        "line\none",
        "λ\\quoted",
    )

    rendered = codec.emit(statement)
    reparsed = codec.parse(rendered)

    assert codec.emit(reparsed) == rendered
    assert rendered.count("py-call") == 1
    assert '!(py-call attack)' in rendered
    assert rendered.startswith("(sn p so ")


def test_batch_places_effects_inside_one_outer_query(runtime) -> None:
    builder = SnarsProgramBuilder(runtime)
    operation = builder.codec.expression(
        "gc",
        builder.codec.symbol("inspect-record"),
    )

    program = builder.batch(
        operation,
        effects=("(sn cycles 1)",),
    )

    assert "!(let* (($gc-effect-1 (sn cycles 1))" in program
    assert program.rstrip().endswith("(gc inspect-record))")
    assert "goalchainer-snars-v1" in program


def test_batch_rejects_non_hyperbase_generated_fact(runtime) -> None:
    builder = SnarsProgramBuilder(runtime)
    operation = builder.codec.expression(
        "gc",
        builder.codec.symbol("inspect-record"),
    )

    with pytest.raises(SnarsInvalidInputError, match="non-HyperBase"):
        builder.batch(operation, facts=("(attack now)",))


def test_text_ingestion_uses_configured_parser_environment(
    runtime,
    tmp_path,
    monkeypatch,
) -> None:
    parser_python = tmp_path / "python"
    parser_python.write_text("#!/bin/sh\n")
    parser_python.chmod(0o700)
    monkeypatch.setenv("GOALCHAINER_METTABASE_PYTHON", str(parser_python))
    monkeypatch.setattr(
        snars_program,
        "_text_program_in_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("broken dependency")),
    )
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '(hb tree hb1 (sh-atom (tag C c NoRoles ()) "safe"))\n'
                '!(sn ingest! hb1 "request" 1.0 1.0)'
            ),
            stderr="",
        )

    monkeypatch.setattr(snars_program.subprocess, "run", run)

    fragments = SnarsProgramBuilder(runtime).text_ingestion(
        '") !(import! &self attack)',
        source="request",
        trust=1.0,
    )

    assert fragments.effects == ('(sn ingest! hb1 "request" 1.0 1.0)',)
    assert calls[0][0][0] == str(parser_python)
    assert calls[0][1]["input"].startswith("{")
    assert "import!" in calls[0][1]["input"]
    assert calls[0][1]["check"] is False


def test_text_ingestion_rejects_invalid_configured_parser_python(
    runtime,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GOALCHAINER_METTABASE_PYTHON", "/missing/parser-python")
    monkeypatch.setattr(
        snars_program,
        "_text_program_in_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("broken dependency")),
    )

    with pytest.raises(SnarsInvalidInputError, match="not an executable"):
        SnarsProgramBuilder(runtime).text_ingestion(
            "request",
            source="request",
            trust=1.0,
        )


# am[verifies i-gc-store-one-request]
def test_text_ingestion_names_each_ingestions_edges_apart(runtime, monkeypatch) -> None:
    # Mettabase names every program's edges from hb1 afresh, so two requests' programs collide in one store.
    program = (
        '(hb edge hb1 (is/Pv.so logs/Cc public/Ca))\n'
        '(hb edge hb1_1 logs/Cc)\n'
        '(hb subedge hb1 hb1_1)\n'
        '(hb tree hb1 (sh-atom (tag C c NoRoles ()) "public"))\n'
        '!(sn ingest! hb1 "request" 1.0 1.0)'
    )
    monkeypatch.setattr(snars_program, "_text_program_in_process", lambda *args, **kwargs: program)
    builder = SnarsProgramBuilder(runtime)

    first, again, second = (
        builder.text_ingestion(text, source="request", trust=1.0) for text in ("first", "first", "second")
    )

    def declared(fragments):
        return {builder.codec.parse(fact)[2].text for fact in fragments.facts if fact.startswith("(hb edge ")}

    assert first == again
    assert len(declared(first)) == len(declared(second)) == 2
    assert declared(first).isdisjoint(declared(second))
    for fragments in (first, second):
        text = " ".join((*fragments.facts, *fragments.effects))
        root = next(name for name in declared(fragments) if name.startswith("hb1-"))
        assert " hb1 " not in text and " hb1_1)" not in text
        assert fragments.effects == (f'(sn ingest! {root} "request" 1.0 1.0)',)
        assert f"(hb subedge {root} hb1_1-" in text
