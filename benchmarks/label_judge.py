"""Purpose: answer as `semrewrite judge` does, but from the labels of the requests in tests/fixtures/judged_requests.json
and judged_requests_heldout.json, so GOALCHAINER_ELEMENTS=judged with this command gives the decision GoalChainer
reaches when every element is read right. A statement of an element its request states gets the opinion (0.8, 0, 0.2),
the evidence 8 for and 0 against that the keyword policy believes a found label at; any other statement gets the
vacuous opinion, which the judged path skips as the policy asserts nothing for a label it does not find. A premise no
fixture labels is an error, so a mismatched request cannot pass as unlabelled."""

# am[implements a-gcje-e2e]

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goal_chainer.judged_elements import STATEMENTS  # noqa: E402

FIXTURES = (ROOT / "tests" / "fixtures" / "judged_requests.json", ROOT / "tests" / "fixtures" / "judged_requests_heldout.json")
# The keyword policy's evidence for a found label, (8, 0), as an opinion: b = 8/10, u = 2/10.
FOUND = (0.8, 0.0, 0.2)

parser = argparse.ArgumentParser(prog="semrewrite")
parser.add_argument("command", choices=("judge",))
parser.add_argument("--judge", required=True)
parser.add_argument("--trust", type=float, required=True)
parser.add_argument("--base-rate", type=float, required=True)
args = parser.parse_args()

labels = {r["text"]: r for path in FIXTURES for r in json.loads(path.read_text())["requests"]}
element_of = {statement: element for element, statements in STATEMENTS.items() for statement in statements}
for number, line in enumerate(sys.stdin, start=1):
    row = json.loads(line)
    request = labels.get(row["premise"])
    if request is None:
        print(f"semrewrite: line {number}: no fixture labels the request {row['premise']!r}", file=sys.stderr)
        sys.exit(1)
    b, d, u = FOUND if request[element_of[row["conclusion"]]] else (0.0, 0.0, 1.0)
    print(json.dumps({"premise": row["premise"], "conclusion": row["conclusion"], "projection": b + args.base_rate * u,
                      "belief": b, "disbelief": d, "uncertainty": u, "base_rate": args.base_rate}))
