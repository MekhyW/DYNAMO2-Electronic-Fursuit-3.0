from __future__ import annotations
import argparse
import importlib
import logging
import multiprocessing as mp
import os
import signal
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Iterable, Sequence


SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

LOG_FORMAT = "%(asctime)s [%(levelname)s] dynamo-supervisor: %(message)s"
log = logging.getLogger("dynamo-supervisor")

NODES = ["mqttbridge", "windows", "unity", "leds", "actuators", "microphone", "desktop_audio", "vision", "voicemod", "audio_sfx", "handheld", "telegram"]
DEFAULT_RESTART_DELAY = 2.0
MAX_RESTART_DELAY = 30.0
MONITOR_INTERVAL = 0.25


def _run_node(module_name: str) -> None:
    """Import and run one node in a child process."""
    module = importlib.import_module(module_name)
    node_main = getattr(module, "main", None)
    if not callable(node_main):
        raise RuntimeError(f"Node module {module_name!r} does not expose main()")
    sys.argv = [str(SRC_DIR / f"{module_name}.py")] # Node CLIs use argparse. Do not leak the supervisor's command-line options into a node when DYNAMO-2.py itself was started with options.
    node_main()

def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start and supervise the DYNAMO-2 runtime nodes.")
    parser.add_argument("--node", dest="nodes", action="append", choices=NODES, help="Start only this node (repeat the option to select several).")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart a node that exits unexpectedly.")
    parser.add_argument("--restart-delay", type=float, default=DEFAULT_RESTART_DELAY, metavar="SECONDS", help=f"Initial delay before restarting a failed node (default: {DEFAULT_RESTART_DELAY}).")
    parser.add_argument("--list-nodes", action="store_true", help="List available nodes and exit.")
    args = parser.parse_args(argv)
    if args.restart_delay < 0:
        parser.error("--restart-delay must be non-negative")
    return args

def _select_nodes(requested: Iterable[str] | None) -> list[str]:
    if not requested:
        return list(NODES)
    selected = set(requested)
    return [spec for spec in NODES if spec in selected]

def _spawn_node(context: mp.context.BaseContext, spec: str) -> mp.Process:
    process = context.Process(target=_run_node, args=(spec,), name=f"DYNAMO-{spec}", daemon=False,)
    process.start()
    log.info("Started %-10s (pid=%s)", spec, process.pid)
    return process

def _stop_processes(processes: dict[str, mp.Process], timeout: float = 5.0) -> None:
    """Stop all children and avoid leaving orphaned node processes behind."""
    live_processes = [process for process in processes.values() if process.is_alive()]
    if not live_processes:
        return
    log.info("Stopping %d node process(es)...", len(live_processes))
    for process in live_processes:
        process.terminate()
    deadline = time.monotonic() + timeout
    for process in live_processes:
        remaining = max(0.0, deadline - time.monotonic())
        process.join(remaining)
    for process in live_processes:
        if process.is_alive():
            log.warning("Node %s did not stop; killing it", process.name)
            process.kill()
            process.join()

def run_supervisor(specs: Sequence[str], *, restart: bool = True, restart_delay: float = DEFAULT_RESTART_DELAY,) -> int:
    """Run ``specs`` until interrupted, restarting failed nodes when enabled."""
    if not specs:
        log.warning("No nodes selected; nothing to start")
        return 0
    context = mp.get_context("spawn")
    processes: dict[str, mp.Process] = {}
    restart_at: dict[str, float] = {}
    failure_count: dict[str, int] = {}
    stop_requested = False
    result = 0
    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        nonlocal stop_requested
        if not stop_requested:
            log.info("Received signal %d; shutting down", signum)
        stop_requested = True
    previous_sigint = signal.signal(signal.SIGINT, request_shutdown)
    previous_sigterm = signal.signal(signal.SIGTERM, request_shutdown)
    try:
        for spec in specs:
            try:
                processes[spec] = _spawn_node(context, spec)
            except Exception:
                log.exception("Could not start node %s", spec)
                if not restart:
                    return 1
                restart_at[spec] = time.monotonic() + restart_delay
        while not stop_requested:
            now = time.monotonic()
            for spec in specs:
                process = processes.get(spec)
                if process is not None and process.is_alive():
                    continue
                if process is not None:
                    exit_code = process.exitcode
                    process.join(timeout=0)
                    processes.pop(spec, None)
                    if stop_requested:
                        continue
                    failure_count[spec] = failure_count.get(spec, 0) + 1
                    log.error("Node %s exited with code %s (failure #%d)", spec, exit_code, failure_count[spec],)
                    if not restart:
                        result = 1
                        stop_requested = True
                        continue
                    delay = min(MAX_RESTART_DELAY,restart_delay * (2 ** min(failure_count[spec] - 1, 4)),) # Exponential backoff keeps a missing optional dependency from producing a tight crash/restart loop.
                    restart_at[spec] = now + delay
                if restart and now >= restart_at.get(spec, now):
                    try:
                        processes[spec] = _spawn_node(context, spec)
                        restart_at.pop(spec, None)
                    except Exception:
                        log.exception("Could not restart node %s", spec)
                        restart_at[spec] = now + restart_delay
            time.sleep(MONITOR_INTERVAL)
    except KeyboardInterrupt:
        stop_requested = True
    finally:
        _stop_processes(processes)
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.list_nodes:
        for spec in NODES:
            print(spec)
        return 0
    os.chdir(SRC_DIR)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%H:%M:%S")
    selected = _select_nodes(args.nodes)
    log.info("Starting nodes: %s", ", ".join(selected))
    return run_supervisor(selected, restart=not args.no_restart, restart_delay=args.restart_delay,)


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
