#!/usr/bin/env python3
"""
publish_ss_json_http.py

On h1:
  - Runs `ss -tin` inside Mininet hosts (hs1, hs2, ...)
  - Parses using your existing parse_ss_tin_output() (from parse_ss_tin_output.py)
  - Writes JSON snapshots to an output directory (one file per host + index.json)
  - Serves that directory over HTTP (default: 127.0.0.1:8000)

Examples:
  python3 publish_ss_json_http.py --range 1-4 --interval 1 --out-dir /home/ubuntu/AQM_CCA/telemetry/ss_tin --port 8000
  python3 publish_ss_json_http.py --hosts hs1,hs3 --interval 2
  python3 publish_ss_json_http.py --range 1-8 --interval 0   # one-shot write then serve

From your Windows laptop (PowerShell):
  ssh -L 8000:127.0.0.1:8000 ubuntu@h1
Then open:
  http://localhost:8000/index.json
  http://localhost:8000/hs1_ss_tin.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import subprocess
import sys

# ---- Reuse your existing parser script ----
# Your screenshot shows: scripts/parse_ss_tin_output.py
# It should expose: parse_ss_tin_output(ss_tin_output: str) -> dict
try:
    from parse_ss_tin_output import parse_ss_tin_output  # type: ignore
except Exception as e:
    print(
        "ERROR: Could not import parse_ss_tin_output.\n"
        "Make sure this script is in the same folder as parse_ss_tin_output.py\n"
        "and that file defines parse_ss_tin_output(ss_tin_output: str) -> dict\n\n"
        f"Import error: {e}",
        file=sys.stderr,
    )
    raise SystemExit(1)


def parse_host_list(hosts_csv: Optional[str], host_range: Optional[str], prefix: str) -> List[str]:
    if hosts_csv:
        return [h.strip() for h in hosts_csv.split(",") if h.strip()]
    if host_range:
        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", host_range)
        if not m:
            raise SystemExit("--range must be like 1-8")
        a, b = int(m.group(1)), int(m.group(2))
        if b < a:
            a, b = b, a
        return [f"{prefix}{i}" for i in range(a, b + 1)]
    raise SystemExit("Provide either --hosts hs1,hs2 or --range 1-8")


def run_ss_tin_on_host(m_path: str, host: str, timeout: int) -> Tuple[int, str, str]:
    """
    Runs `ss -tin` in a Mininet host using `/home/ubuntu/mininet/util/m hs<i> ...`.
    Tries a few invocation patterns since wrappers vary.
    """
    attempts: List[List[str]] = [
        [m_path, host, "ss", "-tin"],
        [m_path, host, "bash", "-lc", "ss -tin"],
        [m_path, host, "sh", "-lc", "ss -tin"],
        [m_path, host, "ss -tin"],
    ]

    last_rc, last_out, last_err = 1, "", ""
    for cmd in attempts:
        try:
            p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
            out = p.stdout or ""
            err = p.stderr or ""
            looks_like_ss = ("State" in out and "Recv-Q" in out and "Send-Q" in out) or ("ESTAB" in out)

            if p.returncode == 0 and looks_like_ss:
                return p.returncode, out, err

            last_rc, last_out, last_err = p.returncode, out, err
        except subprocess.TimeoutExpired as e:
            last_rc = 124
            last_out = e.stdout or ""
            last_err = e.stderr or f"timeout after {timeout}s"

    return last_rc, last_out, last_err


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def collect_and_write(hosts: List[str], m_path: str, out_dir: Path, timeout: int) -> Dict[str, Any]:
    """
    Collects & writes:
      - {host}_ss_tin.json per host
      - index.json
    Returns index structure.
    """
    now = datetime.now(timezone.utc).isoformat()

    index: Dict[str, Any] = {
        "updated_at_utc": now,
        "out_dir": str(out_dir),
        "hosts": [],
    }

    for host in hosts:
        rc, out, err = run_ss_tin_on_host(m_path, host, timeout=timeout)

        record: Dict[str, Any]
        if rc == 0 and out.strip():
            parsed = parse_ss_tin_output(out)
            # Ensure host and capture time are present at top-level meta
            parsed_meta = parsed.get("meta", {}) if isinstance(parsed, dict) else {}
            if isinstance(parsed_meta, dict):
                parsed_meta.setdefault("captured_at_utc", now)
                parsed_meta["mininet_host"] = host
            parsed["meta"] = parsed_meta  # type: ignore

            record = parsed
            n_sockets = len(parsed.get("sockets", []) or []) if isinstance(parsed, dict) else 0

            host_file = f"{host}_ss_tin.json"
            atomic_write_text(out_dir / host_file, json.dumps(record, indent=2, ensure_ascii=False))
            index["hosts"].append(
                {"host": host, "file": host_file, "ok": True, "rc": rc, "n_sockets": n_sockets}
            )
        else:
            # Write an error file so Grafana/you can see failures too
            host_file = f"{host}_ss_tin_error.json"
            record = {
                "meta": {"captured_at_utc": now, "mininet_host": host, "ok": False, "rc": rc},
                "error": (err or "").strip(),
                "stdout_head": (out or "")[:2000],
            }
            atomic_write_text(out_dir / host_file, json.dumps(record, indent=2, ensure_ascii=False))
            index["hosts"].append(
                {"host": host, "file": host_file, "ok": False, "rc": rc, "n_sockets": 0}
            )

    atomic_write_text(out_dir / "index.json", json.dumps(index, indent=2, ensure_ascii=False))
    return index


def start_collector_thread(
    hosts: List[str],
    m_path: str,
    out_dir: Path,
    timeout: int,
    interval: float,
) -> threading.Thread:
    """
    Background thread that refreshes JSON snapshots periodically.
    If interval == 0, does one collection and returns.
    """
    def loop() -> None:
        # Always do an initial collection
        collect_and_write(hosts, m_path, out_dir, timeout)

        if interval <= 0:
            return

        while True:
            time.sleep(interval)
            try:
                collect_and_write(hosts, m_path, out_dir, timeout)
            except Exception as e:
                # Keep the server alive even if one collection fails
                err_obj = {
                    "meta": {"captured_at_utc": datetime.now(timezone.utc).isoformat()},
                    "error": f"collector exception: {type(e).__name__}: {e}",
                }
                atomic_write_text(out_dir / "collector_error.json", json.dumps(err_obj, indent=2))

    t = threading.Thread(target=loop, name="ss_tin_collector", daemon=True)
    t.start()
    return t


def serve_directory(out_dir: Path, bind: str, port: int) -> None:
    handler = partial(SimpleHTTPRequestHandler, directory=str(out_dir))
    httpd = ThreadingHTTPServer((bind, port), handler)
    print(f"[HTTP] Serving {out_dir} at http://{bind}:{port}/")
    print(f"[HTTP] Try: http://{bind}:{port}/index.json")
    httpd.serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect ss -tin per Mininet host into JSON and serve over HTTP.")
    ap.add_argument("--m-path", default="/home/ubuntu/mininet/util/m", help="Path to Mininet wrapper (default: /home/ubuntu/mininet/util/m)")
    ap.add_argument("--hosts", default=None, help="Comma list: hs1,hs2,hs3")
    ap.add_argument("--range", dest="host_range", default=None, help="Range: 1-8 (combined with --prefix)")
    ap.add_argument("--prefix", default="hs", help="Prefix for --range (default: hs)")
    ap.add_argument("--out-dir", default="/home/ubuntu/AQM_CCA/telemetry/ss_tin", help="Directory to write JSON files")
    ap.add_argument("--timeout", type=int, default=10, help="Timeout seconds per host ss call")
    ap.add_argument("--interval", type=float, default=1.0, help="Refresh interval seconds (0 = one-shot write then serve)")
    ap.add_argument("--bind", default="127.0.0.1", help="HTTP bind address (default: 127.0.0.1; use 0.0.0.0 for LAN)")
    ap.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    args = ap.parse_args()

    if not os.path.exists(args.m_path):
        raise SystemExit(f"Mininet wrapper not found: {args.m_path}")

    hosts = parse_host_list(args.hosts, args.host_range, args.prefix)
    out_dir = Path(args.out_dir)

    # Start background collector
    start_collector_thread(hosts, args.m_path, out_dir, args.timeout, args.interval)

    # Serve directory forever
    serve_directory(out_dir, args.bind, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
