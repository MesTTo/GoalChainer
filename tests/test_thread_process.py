"""Purpose: test ThreadProcessSupervisor's bounds on a worker process (output capture, idle, workspace activity, output,
lease and spawn failure), timing each Python child from its own readiness signal so a slow interpreter start-up, as a
loaded machine gives, counts against neither the idle nor the wall limit."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from goal_chainer.thread_models import ThreadProcessObservation, ThreadSupervision
from goal_chainer.thread_process import ThreadProcessSupervisor

# A start-up slower than the 1-second idle limit and the margins the children leave inside it, as a loaded machine
# gives Python; the children must behave the same with it as without.
START_DELAYS = (0.0, 1.5)


def supervision(
    *,
    lease: int = 2,
    idle: int = 2,
    wall: int = 4,
) -> ThreadSupervision:
    return ThreadSupervision(
        lease_seconds=lease,
        idle_timeout_seconds=idle,
        wall_timeout_seconds=wall,
        max_retries=0,
    )


# am[verifies i-gc-thread-test-wallclock]
class ReadinessClock:
    """The supervisor's clock for a child that signals readiness by creating a file once its interpreter runs: zero
    until the file appears, then the seconds since it appeared, so the idle and wall limits count from the child's
    readiness rather than its launch, however long its start-up takes. It adds no limit of its own: a child that exits
    before signalling readiness ends the run as an exited process, which the test's assertions then refuse."""

    def __init__(self, signal: Path) -> None:
        self.signal = signal
        self.ready: float | None = None

    def __call__(self) -> float:
        now = time.monotonic()
        if self.ready is None and self.signal.exists():
            self.ready = now
        return 0.0 if self.ready is None else now - self.ready


# am[verifies i-gc-thread-test-wallclock]
def run_ready(
    tmp_path: Path,
    body: str,
    *,
    limits: ThreadSupervision,
    start_delay: float = 0.0,
    output_limit: int | None = None,
    use_pty: bool = True,
) -> ThreadProcessObservation:
    """Run `body` as a Python child that first signals readiness by creating `ready` in its workspace, after
    `start_delay` seconds of start-up before its interpreter runs, timed by a ReadinessClock on that signal."""

    clock = ReadinessClock(tmp_path / "ready")
    supervisor = (
        ThreadProcessSupervisor(monotonic=clock)
        if output_limit is None
        else ThreadProcessSupervisor(output_limit=output_limit, monotonic=clock)
    )
    script = "import pathlib\npathlib.Path('ready').touch()\n" + body
    return supervisor.run(
        ["sh", "-c", 'sleep "$0"; exec "$@"', str(start_delay), sys.executable, "-c", script],
        cwd=tmp_path,
        supervision=limits,
        use_pty=use_pty,
    )


# am[verifies i-gc-thread-test-wallclock]
@pytest.mark.parametrize("start_delay", START_DELAYS)
def test_process_captures_combined_pty_output(tmp_path, start_delay) -> None:
    result = run_ready(
        tmp_path,
        "import sys\nprint('stdout')\nprint('stderr', file=sys.stderr)\n",
        limits=supervision(),
        start_delay=start_delay,
    )

    assert result.exit_reason == "process-exited"
    assert result.exit_code == 0
    assert "stdout" in result.output
    assert "stderr" in result.output


# am[verifies i-gc-thread-test-wallclock]
@pytest.mark.parametrize("start_delay", START_DELAYS)
def test_process_enforces_idle_timeout(tmp_path, start_delay) -> None:
    result = run_ready(
        tmp_path,
        "import time\ntime.sleep(5)\n",
        limits=supervision(idle=1, wall=3),
        start_delay=start_delay,
    )

    assert result.exit_reason == "idle-timeout"
    assert result.exit_code < 0


# am[verifies i-gc-thread-test-wallclock]
@pytest.mark.parametrize("start_delay", START_DELAYS)
def test_workspace_changes_count_as_passive_activity(tmp_path, start_delay) -> None:
    # After its readiness the child prints nothing and changes the workspace every 0.6 s for 1.2 s, longer than the
    # 1-second idle limit, so only the changes keep it alive.
    result = run_ready(
        tmp_path,
        "import pathlib,time\n"
        "p=pathlib.Path('activity.txt')\n"
        "time.sleep(.6);p.write_text('one')\n"
        "time.sleep(.6);p.write_text('two')\n",
        limits=supervision(idle=1, wall=3),
        start_delay=start_delay,
    )

    assert result.exit_reason == "process-exited"
    assert result.activity_events >= 2


# am[verifies i-gc-thread-test-wallclock]
@pytest.mark.parametrize("start_delay", START_DELAYS)
def test_process_enforces_output_limit(tmp_path, start_delay) -> None:
    result = run_ready(
        tmp_path,
        "print('x' * 1000)\n",
        limits=supervision(),
        start_delay=start_delay,
        output_limit=128,
    )

    assert result.exit_reason == "output-limit"
    assert result.output_bytes == 128


def test_failed_lease_renewal_terminates_process(tmp_path) -> None:
    renewals = 0

    def reject_renewal() -> bool:
        nonlocal renewals
        renewals += 1
        return False

    result = ThreadProcessSupervisor().run(
        [
            sys.executable,
            "-u",
            "-c",
            ("import time\nprint('alive')\ntime.sleep(5)\n"),
        ],
        cwd=tmp_path,
        supervision=supervision(lease=1, idle=2, wall=3),
        renew_lease=reject_renewal,
    )

    assert renewals == 1
    assert result.exit_reason == "lease-expired"


# am[verifies i-gc-thread-test-wallclock]
def test_pipe_mode_and_missing_executable_are_defined(tmp_path: Path) -> None:
    piped = run_ready(tmp_path, "print('pipe')\n", limits=supervision(), use_pty=False)
    missing = ThreadProcessSupervisor().run(
        ["goalchainer-command-that-does-not-exist"],
        cwd=tmp_path,
        supervision=supervision(),
    )

    assert piped.exit_reason == "process-exited"
    assert piped.output.strip() == "pipe"
    assert missing.exit_reason == "spawn-failed"
    assert missing.exit_code == 127
