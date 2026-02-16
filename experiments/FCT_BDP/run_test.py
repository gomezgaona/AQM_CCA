#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def find_mininet_m() -> str:
    candidates = [
        Path.cwd() / "mininet" / "util" / "m",
        Path("/home/ubuntu/mininet/util/m"),
        Path("/usr/share/mininet/util/m"),
        Path("/usr/local/mininet/util/m"),
    ]
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p.resolve())

    which = shutil.which("m")
    if which:
        return which

    raise FileNotFoundError("Could not find Mininet util/m. Tried ./mininet/util/m and /home/ubuntu/mininet/util/m.")


def cleanup_stuck_shells() -> None:
    # These shells appear when m gets invoked without a valid command.
    subprocess.run(
        ["bash", "-lc", "sudo -n pkill -f \"bash --norc --noediting -is mininet:hs\" || true"],
        check=False,
    )


def tail_file(path: Path, n: int = 50) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def run_batch(
    m_path: str,
    host_ids: Iterable[int],
    ip_prefix: str,
    nbytes: str,
    results_dir: Path,
    timeout_s: int,
) -> int:
    """
    Launch a batch in parallel and wait, killing any that exceed timeout_s.
    Returns number of failures.
    """
    procs: Dict[int, subprocess.Popen] = {}
    err_files: Dict[int, object] = {}
    deadlines: Dict[int, float] = {}

    for i in host_ids:
        out_json = results_dir / f"hs{i}_out.json"
        err_log = results_dir / f"hs{i}_err.log"

        # Use iperf3 --logfile to avoid shell redirection and quoting issues.
        # Keep stderr in a separate log.
        cmd = [
            m_path,
            f"hs{i}",
            "iperf3",
            "-c",
            f"{ip_prefix}.{i}",
            "-J",
            "-n",
            nbytes,
            "--logfile",
            str(out_json),
        ]

        # Open err log in the root namespace (shared FS), capture stderr there.
        err_f = err_log.open("w", encoding="utf-8")
        err_files[i] = err_f

        p = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=err_f,
            start_new_session=True,  # lets us kill the whole group on timeout
        )
        procs[i] = p
        deadlines[i] = time.time() + timeout_s

    failures = 0
    alive = set(procs.keys())

    while alive:
        now = time.time()
        finished: List[Tuple[int, int]] = []
        timed_out: List[int] = []

        for i in list(alive):
            p = procs[i]
            rc = p.poll()
            if rc is not None:
                finished.append((i, rc))
                continue
            if now >= deadlines[i]:
                timed_out.append(i)

        for i, rc in finished:
            alive.discard(i)
            if rc != 0:
                failures += 1
                print(f"[hs{i}] FAILED rc={rc}")
                t = tail_file(results_dir / f"hs{i}_err.log", 60)
                if t:
                    print(f"[hs{i}] err.log tail:\n{t}\n")

        for i in timed_out:
            alive.discard(i)
            failures += 1
            print(f"[hs{i}] FAILED timeout after {timeout_s}s, killing process group")
            try:
                os.killpg(procs[i].pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                procs[i].wait(timeout=5)
            except Exception:
                pass
            t = tail_file(results_dir / f"hs{i}_err.log", 60)
            if t:
                print(f"[hs{i}] err.log tail:\n{t}\n")

        time.sleep(0.2)

    # Close stderr files
    for f in err_files.values():
        try:
            f.close()
        except Exception:
            pass

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="Run parallel iperf3 clients from Mininet hs1..hsN and save JSON output.")
    ap.add_argument("num_hosts", type=int, help="Number of Mininet hosts (hs1..hsN).")
    ap.add_argument("--ip-prefix", default="172.17.0", help="Destination IP prefix (default: 172.17.0).")
    ap.add_argument("--nbytes", default="10g", help="iperf3 -n value (default: 10g).")
    ap.add_argument("--results-dir", default="/home/ubuntu/results", help="Output directory (default: /home/ubuntu/results).")
    ap.add_argument("--concurrency", type=int, default=8, help="How many clients to run at once (default: 8).")
    ap.add_argument("--timeout", type=int, default=900, help="Per host timeout in seconds (default: 900).")
    ap.add_argument("--cleanup", action="store_true", help="Kill stuck interactive mininet shells before starting.")
    ap.add_argument("--chown-ubuntu", action="store_true", help="Chown results to ubuntu:ubuntu at the end (when run as root).")
    args = ap.parse_args()

    if args.num_hosts < 1:
        print("num_hosts must be >= 1")
        return 2

    if args.cleanup:
        cleanup_stuck_shells()

    m_path = find_mininet_m()
    results_dir = Path(args.results_dir).expanduser().resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    total = args.num_hosts
    conc = max(1, args.concurrency)

    print(f"Using m: {m_path}")
    print(f"Results: {results_dir}")
    print(f"Hosts: 1..{total}, concurrency={conc}, nbytes={args.nbytes}, ip-prefix={args.ip_prefix}")
    print("Starting...")

    failures = 0
    done = 0
    i = 1
    while i <= total:
        batch = list(range(i, min(total, i + conc - 1) + 1))
        done += len(batch)
        print(f"Running batch {batch[0]}..{batch[-1]} ({done}/{total})")

        failures += run_batch(
            m_path=m_path,
            host_ids=batch,
            ip_prefix=args.ip_prefix,
            nbytes=args.nbytes,
            results_dir=results_dir,
            timeout_s=args.timeout,
        )
        i += conc

    if args.chown_ubuntu and os.geteuid() == 0:
        subprocess.run(["bash", "-lc", f"chown -R ubuntu:ubuntu {results_dir} || true"], check=False)

    print(f"Done. failures={failures}. JSON outputs are in {results_dir}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
