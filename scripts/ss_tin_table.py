#!/usr/bin/env python3
"""
ss_tin_table.py

Print a well organized CLI table from `ss -tin` using your existing
`parse_ss_tin_output(ss_tin_output: str) -> dict` function.

Expected parser shape (from your earlier function):
  parsed = {
    "meta": {...},
    "sockets": [
      {
        "state": "...",
        "recv_q": int,
        "send_q": int,
        "local": {"raw": "...", "ip": "...", "port": int},
        "peer":  {"raw": "...", "ip": "...", "port": int},
        "metrics": {...},     # includes "cc", key:value pairs, "groups", "flags"
        ...
      }, ...
    ]
  }

Usage examples:
  python3 ss_tin_table.py
  python3 ss_tin_table.py --wide
  python3 ss_tin_table.py --input ss_raw.txt
  python3 ss_tin_table.py --details 2
  python3 ss_tin_table.py --json-out ss_parsed.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

# You already created this function earlier. Import it here.
# Change the module name if you saved it differently.
try:
    from parse_ss_tin_output import parse_ss_tin_output  # type: ignore
except Exception as e:
    print(
        "ERROR: Could not import parse_ss_tin_output.\n"
        "Make sure you have a file named 'parse_ss_tin.py' in the same folder\n"
        "and it defines parse_ss_tin_output(ss_tin_output: str).\n\n"
        f"Import error: {e}",
        file=sys.stderr,
    )
    sys.exit(1)


def fmt_value(v: Any) -> str:
    """Human friendly formatting for values produced by the parser."""
    if v is None:
        return ""
    if isinstance(v, dict):
        # unit style: {"value": 123, "unit": "bps"}
        if "value" in v and "unit" in v and len(v) == 2:
            return f"{v['value']}{v['unit']}"
        # pair style: {"a": 1.2, "b": 0.3}
        if "a" in v and "b" in v and len(v) == 2:
            return f"{v['a']}/{v['b']}"
        # generic dict
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    if isinstance(v, list):
        return ",".join(fmt_value(x) for x in v)
    return str(v)


def get_metric(sock: Dict[str, Any], key: str, default: Any = "") -> Any:
    metrics = sock.get("metrics", {}) or {}
    return metrics.get(key, default)


def get_group_metric(sock: Dict[str, Any], group: str, key: str, default: Any = "") -> Any:
    metrics = sock.get("metrics", {}) or {}
    groups = metrics.get("groups", {}) or {}
    g = groups.get(group, {}) or {}
    return g.get(key, default)


def has_flag(sock: Dict[str, Any], flag: str) -> bool:
    metrics = sock.get("metrics", {}) or {}
    flags = metrics.get("flags", []) or []
    return flag in flags


def ellipsize(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + "…"


def build_rows(parsed: Dict[str, Any], wide: bool) -> Tuple[List[str], List[List[str]]]:
    sockets: List[Dict[str, Any]] = parsed.get("sockets", []) or []

    if wide:
        headers = [
            "#",
            "State",
            "Local",
            "Peer",
            "CC",
            "rtt",
            "cwnd",
            "send",
            "pacing_rate",
            "delivery_rate",
            "bytes_sent",
            "bytes_recv",
            "minrtt",
            "bbr_bw",
            "bbr_mrtt",
            "Flags",
        ]
    else:
        headers = [
            "#",
            "State",
            "Local",
            "Peer",
            "CC",
            "rtt",
            "cwnd",
            "send",
            "delivery_rate",
            "bbr_bw",
            "Flags",
        ]

    rows: List[List[str]] = []
    for i, s in enumerate(sockets):
        local_raw = (s.get("local", {}) or {}).get("raw", "") or ""
        peer_raw = (s.get("peer", {}) or {}).get("raw", "") or ""

        cc = get_metric(s, "cc", "")

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

        flags_list = []
        metrics = s.get("metrics", {}) or {}
        for f in (metrics.get("flags", []) or []):
            flags_list.append(str(f))
        flags = ",".join(flags_list)

        if wide:
            row = [
                str(i),
                str(s.get("state", "")),
                local_raw,
                peer_raw,
                fmt_value(cc),
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
                fmt_value(cc),
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

    # Column caps. Tweak if you want.
    cap_by_header = {
        "#": 4,
        "State": 7,
        "Local": 34,
        "Peer": 34,
        "CC": 6,
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

    # Compute initial widths from data, then cap them
    cols = len(headers)
    widths = []
    for ci in range(cols):
        header = headers[ci]
        max_cell = max((len(r[ci]) for r in rows), default=0)
        w = max(len(header), max_cell)
        w = min(w, cap_by_header.get(header, w))
        widths.append(w)

    # If too wide, progressively shrink Local, Peer, Flags, then others
    def total_width(ws: List[int]) -> int:
        # " | " separators between columns
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

    # Render
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
        raise SystemExit(f"--details index out of range. Got {idx}. Valid 0..{len(sockets)-1}")

    s = sockets[idx]
    # Pretty print a compact, useful subset first
    local = (s.get("local", {}) or {}).get("raw", "")
    peer = (s.get("peer", {}) or {}).get("raw", "")
    print(f"Socket #{idx}")
    print(f"State: {s.get('state','')}")
    print(f"Local: {local}")
    print(f"Peer : {peer}")
    print()

    # Full record as JSON for easy copy/paste into analysis
    print(json.dumps(s, indent=2, ensure_ascii=False))


def read_input_text(path: Optional[str]) -> str:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    # Live capture
    return subprocess.check_output(["ss", "-tin"], text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Show ss -tin as a CLI table using parse_ss_tin_output().")
    ap.add_argument("--input", help="Read raw ss -tin text from file instead of running ss.", default=None)
    ap.add_argument("--wide", action="store_true", help="Show more columns.")
    ap.add_argument("--details", type=int, default=None, help="Print full JSON for socket index.")
    ap.add_argument("--json-out", default=None, help="Write parsed JSON to this path.")
    args = ap.parse_args()

    ss_text = read_input_text(args.input)
    parsed = parse_ss_tin_output(ss_text)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)

    if args.details is not None:
        print_details(parsed, args.details)
        return 0

    headers, rows = build_rows(parsed, wide=args.wide)
    print_table(headers, rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
