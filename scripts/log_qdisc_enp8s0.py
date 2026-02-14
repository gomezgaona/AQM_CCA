#!/usr/bin/env python3
"""
qdisc_table_logger.py

Every second:
  - runs: tc -j -s qdisc show dev <iface>
  - prints a table row with fields like your tc JSON output
  - appends JSON lines to a per-run file in the current directory

Run (usually needs sudo):
  sudo python3 qdisc_table_logger.py
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def run_tc(iface: str):
    cmd = ["tc", "-j", "-s", "qdisc", "show", "dev", iface]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or f"tc returned {p.returncode}")
    out = p.stdout.strip()
    return json.loads(out) if out else []


def select_root_qdisc(arr):
    # Prefer the root qdisc object (root:true) if present
    if isinstance(arr, list):
        for q in arr:
            if isinstance(q, dict) and q.get("root") is True:
                return q
        # fallback: first dict
        for q in arr:
            if isinstance(q, dict):
                return q
    return {}


def fmt_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iface", default="enp8s0")
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    # Ensure prints show immediately
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    ts0 = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = Path.cwd() / f"qdisc_{args.iface}_{ts0}.jsonl"

    print(f"Logging to: {out_file}")

    # Table header (matches your JSON fields + options)
    header = (
        f"{'ts':<19} {'kind':<6} {'handle':<7} "
        f"{'rate':>12} {'burst':>10} {'lat':>10} "
        f"{'bytes':>12} {'packets':>10} {'drops':>8} "
        f"{'overlimits':>12} {'requeues':>10} {'backlog':>10} {'qlen':>6}"
    )
    print(header)

    with out_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"start_ts": datetime.now().isoformat(), "iface": args.iface}) + "\n")
        f.flush()

        try:
            while True:
                ts = datetime.now().isoformat(timespec="seconds")

                try:
                    arr = run_tc(args.iface)
                    q = select_root_qdisc(arr)

                    kind = q.get("kind", "-")
                    handle = q.get("handle", "-")

                    opts = q.get("options") if isinstance(q.get("options"), dict) else {}
                    rate = fmt_int(opts.get("rate", 0))
                    burst = fmt_int(opts.get("burst", 0))
                    lat = fmt_int(opts.get("lat", 0))

                    bytes_ = fmt_int(q.get("bytes", 0))
                    packets = fmt_int(q.get("packets", 0))
                    drops = fmt_int(q.get("drops", 0))
                    overlimits = fmt_int(q.get("overlimits", 0))
                    requeues = fmt_int(q.get("requeues", 0))
                    backlog = fmt_int(q.get("backlog", 0))
                    qlen = fmt_int(q.get("qlen", 0))

                    # Print row
                    print(
                        f"{ts:<19} {kind:<6} {handle:<7} "
                        f"{rate:>12} {burst:>10} {lat:>10} "
                        f"{bytes_:>12} {packets:>10} {drops:>8} "
                        f"{overlimits:>12} {requeues:>10} {backlog:>10} {qlen:>6}"
                    )

                    # Log JSON line (store the exact qdisc object like tc returns)
                    f.write(json.dumps({"ts": ts, "iface": args.iface, "qdisc": q}) + "\n")
                    f.flush()

                except Exception as e:
                    # Print error row + log it
                    print(f"{ts:<19} ERROR  -       {str(e)}")
                    f.write(json.dumps({"ts": ts, "iface": args.iface, "error": str(e)}) + "\n")
                    f.flush()

                time.sleep(args.interval)

        except KeyboardInterrupt:
            print("\nStopped.")
            f.write(json.dumps({"end_ts": datetime.now().isoformat(), "iface": args.iface}) + "\n")
            f.flush()


if __name__ == "__main__":
    main()
