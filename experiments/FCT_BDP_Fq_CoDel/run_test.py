#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

DEFAULT_M = "/home/ubuntu/mininet/util/m"
OUT_ROOT = "/home/ubuntu/AQM_CCA/experiments/FCT_BDP_Fq_CoDel"
IP_PREFIX = "172.17.0"


def find_m(m_path):
    if os.path.isfile(m_path) and os.access(m_path, os.X_OK):
        return m_path
    which = shutil.which("m")
    if which:
        return which
    raise SystemExit("ERROR: cannot find Mininet m. Use --m /home/ubuntu/mininet/util/m")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("num_hosts", type=int, help="Number of hosts (hs1..hsN)")
    ap.add_argument("--cca", required=True, help="prague, bbr, cubic, etc.")
    ap.add_argument("--bdp", required=True, help="0.1BDP, 1BDP, 20BDP, etc.")
    ap.add_argument("--nbytes", required=True, help="iperf3 -n value, e.g., 6.25g, 10g")
    ap.add_argument("--ip-prefix", default=IP_PREFIX)
    ap.add_argument("--out-root", default=OUT_ROOT)
    ap.add_argument("--m", default=DEFAULT_M)
    args = ap.parse_args()

    m = find_m(args.m)

    outdir = (Path(args.out_root) / args.bdp / args.cca).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Saving JSON to: {outdir}")
    print(f"Launching hs1..hs{args.num_hosts} concurrently...")

    procs = {}       # host_id -> Popen
    finished = set() # host_ids already counted as finished

    # Start ALL hosts at once
    for i in range(1, args.num_hosts + 1):
        out_json = outdir / f"hs{i}_out.json"
        if out_json.exists():
            out_json.unlink()

        cmd = [
            m, f"hs{i}",
            "iperf3",
            "-c", f"{args.ip_prefix}.{i}",
            "-J",
            "-n", args.nbytes,
            "-C", args.cca,
            "--logfile", str(out_json),   # iperf3 writes JSON here
        ]

        procs[i] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait until the LAST transfer finishes
    total = args.num_hosts
    while len(finished) < total:
        for i, p in procs.items():
            if i in finished:
                continue
            if p.poll() is not None:  # finished
                finished.add(i)
                print(f"Finished {len(finished)}/{total} (hs{i})")
        time.sleep(0.5)

    # Check results after all are done
    failures = 0
    for i, p in procs.items():
        rc = p.returncode
        out_json = outdir / f"hs{i}_out.json"
        empty = (not out_json.exists()) or (out_json.stat().st_size == 0)
        if rc != 0 or empty:
            failures += 1
            print(f"hs{i} FAILED (rc={rc}, empty_json={empty})")

    print(f"Done. failures={failures}")
    raise SystemExit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
