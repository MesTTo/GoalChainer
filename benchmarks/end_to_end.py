"""Purpose: measure GoalChainer's native decision end to end on every labelled request, once per element reading:
keywords (the policy's label lists), judged (the semantic rewriter's judge, through GOALCHAINER_SEMREWRITE) and labels
(benchmarks/label_judge.py, every element read right). Each run is the CLI's demo command in its own process. Its JSON
and a summary of it are kept in the output directory, so an interrupted measurement resumes where it stopped; the
tables go to benchmarks/end_to_end.json: per request and reading, the chosen action, its status and expectation, the
elements SNARS held and the seconds taken; per reading, agreement with the decision under the labels, element accuracy
and the chosen action's mean expectation.

Run from anywhere, with GOALCHAINER_SEMREWRITE naming the semrewrite command:
    python3 benchmarks/end_to_end.py OUTPUT_DIR [--workers N] [--readings keywords,judged,labels,protective]
        [--requests held_out:15,held_out:17]
The protective reading (benchmarks/protective_judge.py) differs from the judged one only on requests the keyword
extractor finds sensitive data in and the judge does not, so it needs running only there.
"""

# am[implements a-gcje-e2e]

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "tuning": ROOT / "tests" / "fixtures" / "judged_requests.json",
    "held_out": ROOT / "tests" / "fixtures" / "judged_requests_heldout.json",
}
RESULTS = ROOT / "benchmarks" / "end_to_end.json"
# The request context's fields and the elements they hold.
CONTEXT = {"sensitive": "sensitive-data", "public": "public-data", "unverified": "unverified",
           "coordination": "coordination-needed"}


# am[implements a-gcje-e2e]
def reading_environments() -> dict[str, dict[str, str]]:
    """The environment each reading runs the demo under."""
    label_judge = shlex.join([sys.executable, str(ROOT / "benchmarks" / "label_judge.py")])
    environments = {"keywords": {"GOALCHAINER_ELEMENTS": "keywords"},
                    "labels": {"GOALCHAINER_ELEMENTS": "judged", "GOALCHAINER_SEMREWRITE": label_judge}}
    semrewrite = os.environ.get("GOALCHAINER_SEMREWRITE", "")
    if semrewrite.strip():
        environments["judged"] = {"GOALCHAINER_ELEMENTS": "judged", "GOALCHAINER_SEMREWRITE": semrewrite}
        protective = shlex.join([sys.executable, str(ROOT / "benchmarks" / "protective_judge.py")])
        environments["protective"] = {"GOALCHAINER_ELEMENTS": "judged", "GOALCHAINER_SEMREWRITE": protective,
                                      "PROTECTIVE_SEMREWRITE": semrewrite}
    return environments


# am[implements a-gcje-e2e]
def summary(payload: dict) -> dict:
    """What the measurement keeps of one decision: the chosen action as solve_incident chooses it, the recommended
    decision or else the first, with its status and SNARS expectation; every action's; and the elements SNARS held."""
    decisions = payload["decisions"]
    chosen = next((d for d in decisions if d["status"] == "recommended"), decisions[0])
    context = payload["request_context"]
    elements = payload.get("elements", {})
    return {
        "chosen": chosen["action_id"], "status": chosen["status"], "expectation": chosen["evidence"]["expectation"],
        "automatic": payload["ranking"]["automatic"], "order": payload["ranking"]["order"],
        "actions": {d["action_id"]: {"status": d["status"], "norm": d["norm_status"],
                                     "expectation": d["evidence"]["expectation"]} for d in decisions},
        "held": {element: context[field]["evidence"]["positive"] > 0
                 and context[field]["opinion"]["expectation"] > 0.5 for field, element in CONTEXT.items()},
        "context": {element: round(context[field]["opinion"]["expectation"], 6) for field, element in CONTEXT.items()},
        "statements": {e: o["statement"] for e, o in elements.get("opinions", {}).items()},
    }


# am[implements a-gcje-e2e]
def run(job: tuple[str, int, str, str], out: Path, environment: dict[str, str]) -> dict:
    """One demo run, or its kept record when an earlier run of the job succeeded."""
    split, index, text, reading = job
    record_path = out / f"{split}-{index:02d}-{reading}.json"
    if record_path.exists():
        kept = json.loads(record_path.read_text())
        if kept["returncode"] == 0:
            return kept
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), **environment}
    start = time.monotonic()
    result = subprocess.run([sys.executable, "-m", "goal_chainer.cli", "demo", "--request", text, "--json"],
                            cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    record = {"split": split, "index": index, "reading": reading, "text": text, "returncode": result.returncode,
              "seconds": round(time.monotonic() - start, 1)}
    if result.returncode == 0:
        payload = json.loads(result.stdout)
        (out / f"{split}-{index:02d}-{reading}.payload.json").write_text(result.stdout)
        record.update(summary(payload))
    else:
        record["error"] = result.stdout.strip()[-4000:] or result.stderr.strip()[-4000:]
    record_path.write_text(json.dumps(record, indent=1) + "\n")
    return record


# am[implements a-gcje-e2e]
def tabulate(records: list[dict], labels: dict[tuple[str, int], dict]) -> dict:
    """Per split and reading: runs that failed, decisions agreeing with the labels reading's, element accuracy of what
    SNARS held, the chosen actions and their mean expectation, and the mean seconds a run took."""
    out: dict = {}
    by = {(r["split"], r["index"], r["reading"]): r for r in records}
    for split in FIXTURES:
        for reading in sorted({r["reading"] for r in records}):
            rows = [r for r in records if r["split"] == split and r["reading"] == reading]
            ok = [r for r in rows if r["returncode"] == 0]
            oracle = [by.get((split, r["index"], "labels")) for r in ok]
            agree = sum(o is not None and o["returncode"] == 0 and o["chosen"] == r["chosen"] for r, o in zip(ok, oracle))
            elements = {e: sum(r["held"][e] == labels[(split, r["index"])][e] for r in ok) for e in CONTEXT.values()}
            actions: dict[str, int] = {}
            for r in ok:
                actions[r["chosen"]] = actions.get(r["chosen"], 0) + 1
            out.setdefault(split, {})[reading] = {
                "runs": len(rows), "failed": len(rows) - len(ok), "agree_with_labels": agree,
                "elements_right": elements, "chosen": actions,
                "mean_expectation": round(sum(r["expectation"] for r in ok) / len(ok), 4) if ok else None,
                "mean_seconds": round(sum(r["seconds"] for r in ok) / len(ok), 1) if ok else None,
            }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 8) // 8))
    parser.add_argument("--readings", default="keywords,judged,labels")
    parser.add_argument("--requests", help="only these requests, as split:index pairs separated by commas, such as "
                        "held_out:15,held_out:17 for a reading that differs from another only there")
    parser.add_argument("--collect", action="store_true",
                        help="run nothing: tabulate every record kept in OUTPUT_DIR")
    args = parser.parse_args()
    if args.collect:
        requests = {split: json.loads(path.read_text())["requests"] for split, path in FIXTURES.items()}
        labels = {(split, i): r for split, rs in requests.items() for i, r in enumerate(rs)}
        records = sorted((json.loads(path.read_text()) for path in args.out.glob("*.json")
                          if not path.name.endswith(".payload.json")),
                         key=lambda r: (r["split"], r["index"], r["reading"]))
        tables = tabulate(records, labels)
        RESULTS.write_text(json.dumps({"tables": tables, "records": records}, indent=1) + "\n")
        print(json.dumps(tables, indent=1))
        return 0 if all(r["returncode"] == 0 for r in records) else 1
    environments = reading_environments()
    wanted = args.readings.split(",")
    missing = [r for r in wanted if r not in environments]
    if missing:
        parser.error(f"no environment for {missing}: judged needs GOALCHAINER_SEMREWRITE")
    args.out.mkdir(parents=True, exist_ok=True)
    requests = {split: json.loads(path.read_text())["requests"] for split, path in FIXTURES.items()}
    labels = {(split, i): r for split, rs in requests.items() for i, r in enumerate(rs)}
    chosen = None if args.requests is None else {(s, int(i)) for s, i in (pair.split(":") for pair in args.requests.split(","))}
    jobs = [(split, i, r["text"], reading) for split, rs in requests.items() for i, r in enumerate(rs) for reading in wanted
            if chosen is None or (split, i) in chosen]
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run, job, args.out, environments[job[3]]): job for job in jobs}
        for done, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            records.append(record)
            outcome = record.get("chosen", f"failed {record['returncode']}")
            print(f"[{done}/{len(jobs)}] {record['split']} {record['index']:02d} {record['reading']}: {outcome} "
                  f"({record['seconds']} s)", flush=True)
    records.sort(key=lambda r: (r["split"], r["index"], r["reading"]))
    tables = tabulate(records, labels)
    RESULTS.write_text(json.dumps({"tables": tables, "records": records}, indent=1) + "\n")
    print(json.dumps(tables, indent=1))
    return 0 if all(r["returncode"] == 0 for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
