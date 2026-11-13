"""Purpose: answer as `semrewrite judge` does with the privacy-protective reading of sensitive data, sensitive when
GoalChainer's keyword extractor or the judge says so, for measuring what that reading costs in decisions. It runs the
real judge, PROTECTIVE_SEMREWRITE naming its command line, and passes every opinion through, except that for a
request the keyword extractor finds sensitive data in and the judge does not, the first sensitive-data statement gets
the opinion (0.8, 0, 0.2): the evidence 8 for and 0 against the keyword policy believes a found label at."""

# am[implements a-gcje-union]

import argparse
import json
import shlex
import subprocess
import sys
from os import environ
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goal_chainer.evidence import _extract_keyword_evidence  # noqa: E402
from goal_chainer.judged_elements import BASE_RATES, STATEMENTS  # noqa: E402

FOUND = (0.8, 0.0, 0.2)
SENSITIVE = STATEMENTS["sensitive-data"]

parser = argparse.ArgumentParser(prog="semrewrite")
parser.add_argument("command", choices=("judge",))
parser.add_argument("--judge", required=True)
parser.add_argument("--trust", type=float, required=True)
parser.add_argument("--base-rate", type=float, required=True)
args = parser.parse_args()

pairs = sys.stdin.read()
inner = subprocess.run([*shlex.split(environ["PROTECTIVE_SEMREWRITE"]), *sys.argv[1:]], input=pairs, text=True,
                       capture_output=True, check=False)
if inner.returncode != 0:
    sys.stderr.write(inner.stderr)
    sys.exit(inner.returncode)
rows = [json.loads(line) for line in inner.stdout.splitlines()]
rate = BASE_RATES["sensitive-data"]
judged_sensitive = {}
for row in rows:
    if row["conclusion"] in SENSITIVE:
        # The judge's projection at the element's base rate, as the judged reading counts it.
        p = row["belief"] + rate * row["uncertainty"]
        judged_sensitive[row["premise"]] = judged_sensitive.get(row["premise"], False) or p > 0.5
for row in rows:
    premise = row["premise"]
    if (row["conclusion"] == SENSITIVE[0] and not judged_sensitive[premise]
            and _extract_keyword_evidence(premise).sensitive_categories):
        b, d, u = FOUND
        row.update(belief=b, disbelief=d, uncertainty=u, projection=b + args.base_rate * u)
    print(json.dumps(row))
