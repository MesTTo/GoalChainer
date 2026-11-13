"""Purpose: stand in for `semrewrite judge` in GoalChainer's tests. It reads (premise, conclusion) JSON lines and answers
each, in order, with the opinion FAKE_JUDGE_BELIEFS gives its conclusion (a JSON object mapping a conclusion to its
belief and disbelief, vacuous when absent), discounted by --trust and at --base-rate, rounded as semrewrite rounds.
FAKE_JUDGE_FAIL set to exit, garbage or sleep makes it exit 3, write a line that is not JSON, or outlast a timeout."""

# am[verifies a-gcje-runner]

import argparse
import json
import os
import sys
import time

parser = argparse.ArgumentParser(prog="semrewrite")
parser.add_argument("command", choices=("judge",))
parser.add_argument("--judge", required=True)
parser.add_argument("--trust", type=float, required=True)
parser.add_argument("--base-rate", type=float, required=True)
args = parser.parse_args()

failure = os.environ.get("FAKE_JUDGE_FAIL", "")
if failure == "exit":
    print(f"semrewrite: fake judge {args.judge} refused", file=sys.stderr)
    sys.exit(3)
if failure == "sleep":
    time.sleep(60)
beliefs = json.loads(os.environ.get("FAKE_JUDGE_BELIEFS", "{}"))
for line in sys.stdin:
    row = json.loads(line)
    belief, disbelief = beliefs.get(row["conclusion"], (0.0, 0.0))
    b, d = args.trust * belief, args.trust * disbelief
    u = 1.0 - b - d
    answer = {
        "premise": row["premise"],
        "conclusion": row["conclusion"],
        "projection": round(b + args.base_rate * u, 6),
        "belief": round(b, 6),
        "disbelief": round(d, 6),
        "uncertainty": round(u, 6),
        "base_rate": round(args.base_rate, 6),
    }
    print("this is not JSON" if failure == "garbage" else json.dumps(answer))
