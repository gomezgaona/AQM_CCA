#!/usr/bin/env python3
"""
ss_tin_table_per_host.py

Show `ss -tin` as a clean CLI table *per Mininet host*, where hosts are accessed via:
  /home/ubuntu/mininet/util/m hs<i>

This script:
  1) runs `ss -tin` inside each specified host via `/home/ubuntu/mininet/util/m`
  2) parses output using your existing `parse_ss_tin_output(ss_tin_output: str) -> dict`
  3) prints a well organized table per host

Requirements:
  - You already have parse_ss_tin_output implemented and importable (example: parse_ss_tin.py in same dir)

Examples:
  python3 ss_tin_table_per_host.py --range 1-4
  python3 ss_tin_table_per_host.py --hosts hs1,hs3,hs7 --wide
  python3 ss_tin_table_per_host.py --range 1-8 --json-dir ss_json
  python3 ss_tin_table_per_host.py --details hs2:0
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Change module name if yours is different.
try:
    from parse_ss_tin_output import parse_ss_tin_output  # type: ignore
except Exception as e:
    print(
        "ERROR: Could not import parse_ss_tin_output.\n"
        "Make sure your parser file is in the same folder (e.g., parse_ss_tin.py)\n"
        "and defines: parse_ss_tin_output(ss_tin_output: str) -> dict\n\n"
        f"Import error: {e}",
        file=sys.stderr,
    )
    sys.exit(1)


# -------------------- Formatting helpers --------------------

def fmt_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        if "value" in v and "unit" in v and len(v) == 2:
            return f"{v['value']}{v['unit']}"
        if "a" in v and "b" in v and len(v) == 2:
            return f"{v['a']}/{v['b']}"
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    if isinstance(v, list):
        return ",".join(fmt_value(x) for x in v)
    return str(v)


def ellipsize(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + "…"


def get_metric(sock: Dict[str, Any], key: str, default: Any = "") -> Any:
    metrics = sock.get("metrics", {}) or {}
    return metrics.get(key, default)


def get_group_metric(sock: Dict[str, Any], group: str, key: str, default: Any = "") -> Any:
    metrics = sock.get("metrics", {}) or {}
    groups = metrics.get("groups", {}) or {}
    g = groups.get(group, {}) or {}
    return g.get(key, default)


def build_rows(parsed: Dict[str, Any], wide: bool) -> Tuple[List[str], List[List[str]]]:
    sockets: List[Dict[str, Any]] = parsed.get("sockets", []) or []

    if wide:
        headers = [
            "#", "State", "Local", "Peer", "CC",
            "rtt", "cwnd", "send", "pacing_rate", "delivery_rate",
            "bytes_sent", "bytes_recv", "minrtt", "bbr_bw", "bbr_mrtt", "Flags",
        ]
    else:
        headers = [
            "#", "State", "Local", "Peer", "CC",
            "rtt", "cwnd", "send", "delivery_rate", "bbr_bw", "Flags",
        ]

    rows: List[List[str]] = []
    for i, s in enumerate(sockets):
        local_raw = (s.get("local", {}) or {}).get("raw", "") or ""
        peer_raw = (s.get("peer", {}) or {}).get("raw", "") or ""

        cc = fmt_value(get_metric(s, "cc", ""))

        rtt = fmt_value(get_metric(s, "rtt", ""))
        cwnd = fmt_value(get_metric(s, "cwnd", ""))

        send = fmt_value(get_metric(s, "send", ""))
        pacing_rate = fmt_value(get_metric(s, "pacing_rate", ""))
        delivery_rate = fmt_value(get_metric(s, "delivery_rate", ""))

        bytes_sent = fmt_value(get_metric(s, "bytes_sent", ""))
        bytes_recv = fmt_value(get_metric(s, "bytes_received", ""))
        minrtt = fmt_value(get_metric(s, "minrtt", ""))

        bbr_bw = fmt_value(get_group_metric(s, "bbr", "bw", ""))
        bbr_mrtt = fmt_value(get_group_metric(s, "bbr", "mrtt", ""))

        metrics = s.get("metrics", {}) or {}
        flags_list = [str(f) for f in (metrics.get("flags", []) or [])]
        flags = ",".join(flags_list)

        if wide:
            row = [
                str(i),
                str(s.get("state", "")),
                local_raw,
                peer_raw,
                cc,
                rtt,
                cwnd,
                send,
                pacing_rate,
                delivery_rate,
                bytes_sent,
                bytes_recv,
                minrtt,
                bbr_bw,
                bbr_mrtt,
                flags,
            ]
        else:
            row = [
                str(i),
                str(s.get("state", "")),
                local_raw,
                peer_raw,
                cc,
                rtt,
                cwnd,
                send,
                delivery_rate,
                bbr_bw,
                flags,
            ]

        rows.append(row)

    return headers, rows


def print_table(headers: List[str], rows: List[List[str]]) -> None:
    term_w = shutil.get_terminal_size((140, 20)).columns

    cap_by_header = {
        "#": 4,
        "State": 7,
        "Local": 34,
        "Peer": 34,
        "CC": 8,
        "rtt": 14,
        "cwnd": 8,
        "send": 14,
        "pacing_rate": 16,
        "delivery_rate": 16,
        "bytes_sent": 12,
        "bytes_recv": 12,
        "minrtt": 12,
        "bbr_bw": 16,
        "bbr_mrtt": 10,
        "Flags": 18,
    }

    cols = len(headers)
    widths: List[int] = []
    for ci in range(cols):
        header = headers[ci]
        max_cell = max((len(r[ci]) for r in rows), default=0)
        w = max(len(header), max_cell)
        w = min(w, cap_by_header.get(header, w))
        widths.append(w)

    def total_width(ws: List[int]) -> int:
        return sum(ws) + 3 * (len(ws) - 1)

    shrink_order = []
    for h in ["Local", "Peer", "Flags", "bytes_sent", "bytes_recv", "pacing_rate", "delivery_rate", "send", "rtt"]:
        if h in headers:
            shrink_order.append(headers.index(h))

    min_width = {i: 6 for i in range(cols)}
    if "Local" in headers:
        min_width[headers.index("Local")] = 18
    if "Peer" in headers:
        min_width[headers.index("Peer")] = 18
    if "Flags" in headers:
        min_width[headers.index("Flags")] = 8

    while total_width(widths) > term_w and shrink_order:
        changed = False
        for idx in shrink_order:
            if total_width(widths) <= term_w:
                break
            if widths[idx] > min_width.get(idx, 6):
                widths[idx] -= 1
                changed = True
        if not changed:
            break

    header_line = " | ".join(ellipsize(h, widths[i]).ljust(widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * widths[i] for i in range(cols))
    print(header_line)
    print(sep_line)

    for r in rows:
        line = " | ".join(ellipsize(r[i], widths[i]).ljust(widths[i]) for i in range(cols))
        print(line)


def print_details(parsed: Dict[str, Any], idx: int) -> None:
    sockets: List[Dict[str, Any]] = parsed.get("sockets", []) or []
    if idx < 0 or idx >= len(sockets):
        raise SystemExit(f"details index out of range: {idx} (valid 0..{len(sockets)-1})")
    print(json.dumps(sockets[idx], indent=2, ensure_ascii=False))


# -------------------- Mininet host execution --------------------

def run_ss_tin_on_host(m_path: str, host: str, timeout: int) -> Tuple[int, str, str, List[List[str]]]:
    """
    Tries several common invocation patterns for `/home/ubuntu/mininet/util/m hsX <command>`.
    Returns: (returncode, stdout, stderr, attempted_cmds)
    """
    attempts: List[List[str]] = [
        [m_path, host, "ss", "-tin"],
        [m_path, host, "ss -tin"],
        [m_path, host, "--", "ss", "-tin"],
        [m_path, host, "-c", "ss -tin"],     # some wrappers use -c
        [m_path, host, "bash", "-lc", "ss -tin"],
    ]

    last_rc, last_out, last_err = 1, "", ""
    for cmd in attempts:
        try:
            p = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            out = p.stdout or ""
            err = p.stderr or ""

            # Heuristic: consider "good" if it looks like ss output
            looks_like_ss = ("State" in out and "Recv-Q" in out and "Send-Q" in out) or ("ESTAB" in out)
            if p.returncode == 0 and looks_like_ss:
                return p.returncode, out, err, attempts

            last_rc, last_out, last_err = p.returncode, out, err
        except subprocess.TimeoutExpired as e:
            last_rc, last_out, last_err = 124, (e.stdout or ""), (e.stderr or f"timeout after {timeout}s")

    return last_rc, last_out, last_err, attempts


def parse_host_list(args_hosts: Optional[str], args_range: Optional[str], prefix: str) -> List[str]:
    if args_hosts:
        return [h.strip() for h in args_hosts.split(",") if h.strip()]

    if args_range:
        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", args_range)
        if not m:
            raise SystemExit("--range must be like 1-8")
        a = int(m.group(1))
        b = int(m.group(2))
        if b < a:
            a, b = b, a
        return [f"{prefix}{i}" for i in range(a, b + 1)]

    raise SystemExit("Provide either --hosts hs1,hs2 or --range 1-8")


# -------------------- Main --------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Show ss -tin table per Mininet host using /home/ubuntu/mininet/util/m hs<i>.")
    ap.add_argument("--m-path", default="/home/ubuntu/mininet/util/m", help="Path to the Mininet host access wrapper.")
    ap.add_argument("--hosts", default=None, help="Comma list, e.g. hs1,hs2,hs3")
    ap.add_argument("--range", dest="host_range", default=None, help="Range, e.g. 1-8 (combined with --prefix)")
    ap.add_argument("--prefix", default="hs", help="Prefix used with --range (default: hs)")
    ap.add_argument("--wide", action="store_true", help="Show wide table.")
    ap.add_argument("--details", default=None, help="Print full JSON for one socket: format host:index, e.g. hs2:0")
    ap.add_argument("--timeout", type=int, default=10, help="Timeout seconds per host command.")
    ap.add_argument("--json-dir", default=None, help="If set, writes parsed JSON per host into this directory.")
    args = ap.parse_args()

    m_path = args.m_path
    if not os.path.exists(m_path):
        raise SystemExit(f"m wrapper not found at: {m_path}")

    hosts = parse_host_list(args.hosts, args.host_range, args.prefix)

    json_dir: Optional[Path] = None
    if args.json_dir:
        json_dir = Path(args.json_dir)
        json_dir.mkdir(parents=True, exist_ok=True)

    details_host: Optional[str] = None
    details_idx: Optional[int] = None
    if args.details:
        if ":" not in args.details:
            raise SystemExit("--details format must be host:index, e.g. hs2:0")
        details_host, idx_s = args.details.split(":", 1)
        if not idx_s.isdigit():
            raise SystemExit("--details index must be an integer")
        details_idx = int(idx_s)

    any_ok = False

    for host in hosts:
        rc, out, err, attempted = run_ss_tin_on_host(m_path, host, args.timeout)

        print()
        print("=" * 80)
        print(f"{host} | ss -tin | {datetime.now().isoformat(timespec='seconds')}")
        print("=" * 80)

        if rc != 0 or not out.strip():
            print(f"ERROR: failed to run ss -tin on {host} (rc={rc})", file=sys.stderr)
            if err.strip():
                print(err.strip(), file=sys.stderr)
            print("Tried commands:", file=sys.stderr)
            for cmd in attempted:
                print("  " + " ".join(cmd), file=sys.stderr)
            continue

        parsed = parse_ss_tin_output(out)
        any_ok = True

        if json_dir is not None:
            (json_dir / f"{host}_ss_tin.json").write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")

        if details_host == host and details_idx is not None:
            print_details(parsed, details_idx)
            # If details is requested, still continue to other hosts (useful)
            continue

        headers, rows = build_rows(parsed, wide=args.wide)
        if not rows:
            print("(no sockets parsed)")
        else:
            print_table(headers, rows)

    return 0 if any_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
