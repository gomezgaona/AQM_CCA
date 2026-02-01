#!/usr/bin/env python3
import json
import re
import subprocess
import socket as pysocket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


RE_HEADER = re.compile(
    r"^(?P<state>\S+)\s+(?P<recvq>\d+)\s+(?P<sendq>\d+)\s+(?P<local>\S+)\s+(?P<peer>\S+)(?:\s+(?P<proc>.*))?$"
)

RE_PAREN_GROUP = re.compile(r"(?P<name>[A-Za-z0-9_]+):\((?P<body>[^)]*)\)")
RE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

RE_INT = re.compile(r"^[+-]?\d+$")
RE_FLOAT = re.compile(r"^[+-]?(?:\d+\.\d*|\d*\.\d+|\d+)$")
RE_NUM_UNIT = re.compile(r"^([+-]?(?:\d+\.\d*|\d*\.\d+|\d+))([A-Za-z%/]+)$")


def split_blocks(ss_output: str) -> List[Tuple[str, List[str]]]:
    """
    Blocks start at a non-indented line (socket header) and include following indented lines.
    Skips the top table header row that begins with 'State'.
    """
    lines = [ln.rstrip("\n") for ln in ss_output.splitlines()]
    blocks: List[Tuple[str, List[str]]] = []

    cur_header: Optional[str] = None
    cur_cont: List[str] = []

    for ln in lines:
        if not ln.strip():
            continue
        if ln.lstrip().startswith("State "):
            continue

        if ln[:1].isspace():
            if cur_header is not None:
                cur_cont.append(ln.strip())
            else:
                # stray continuation, keep anyway
                blocks.append(("", [ln.strip()]))
        else:
            if cur_header is not None:
                blocks.append((cur_header, cur_cont))
            cur_header = ln.strip()
            cur_cont = []

    if cur_header is not None:
        blocks.append((cur_header, cur_cont))

    return blocks


def parse_ip_port(addr_port: str) -> Dict[str, Any]:
    """
    Parses:
      127.0.0.1:55226
      [2001:...:f1da]:22
    Returns raw + ip + port (int when possible).
    """
    out: Dict[str, Any] = {"raw": addr_port, "ip": None, "port": None}

    s = addr_port.strip()
    if s.startswith("["):
        # [IPv6]:port
        m = re.match(r"^\[(?P<ip>.*)\]:(?P<port>\d+)$", s)
        if m:
            out["ip"] = m.group("ip")
            out["port"] = int(m.group("port"))
        return out

    # IPv4:port or hostname:port (take last colon)
    if ":" in s:
        ip, port = s.rsplit(":", 1)
        out["ip"] = ip
        if port.isdigit():
            out["port"] = int(port)
        else:
            out["port"] = port
    else:
        out["ip"] = s

    return out


def coerce_value(s: str) -> Any:
    """
    Turns strings into structured values when reasonable:
      123 -> int
      1.23 -> float
      12,12 -> [12, 12]
      1.929/0.888 -> {"a": 1.929, "b": 0.888}
      51677ms -> {"value": 51677, "unit": "ms"}
      58207107640bps -> {"value": 58207107640, "unit": "bps"}
    Otherwise returns the original string.
    """
    s = s.strip().strip(",")

    if s == "":
        return s

    # pair a/b
    if "/" in s and not s.startswith("/") and not s.endswith("/"):
        left, right = s.split("/", 1)
        left = left.strip()
        right = right.strip()
        if RE_FLOAT.match(left) and RE_FLOAT.match(right):
            a = float(left) if "." in left else int(left)
            b = float(right) if "." in right else int(right)
            return {"a": a, "b": b}

    # comma list
    if "," in s and not any(ch in s for ch in "()[]{}"):
        parts = [p.strip() for p in s.split(",") if p.strip() != ""]
        if parts and all(RE_FLOAT.match(p) for p in parts):
            out = [float(p) if "." in p else int(p) for p in parts]
            return out
        return parts

    # int or float
    if RE_INT.match(s):
        return int(s)
    if RE_FLOAT.match(s):
        return float(s)

    # number with unit
    m = RE_NUM_UNIT.match(s)
    if m:
        num_str = m.group(1)
        unit = m.group(2)
        num = float(num_str) if "." in num_str else int(num_str)
        return {"value": num, "unit": unit}

    return s


def parse_paren_body(body: str) -> Dict[str, Any]:
    """
    Parses the inside of name:(...)
    Example:
      bw:58207107640bps,mrtt:0.012,pacing_gain:2.88672,cwnd_gain:2.88672
    """
    body = body.strip()
    out: Dict[str, Any] = {}

    # Most blobs in ss -tin are comma-separated key:value
    parts = [p.strip() for p in body.split(",") if p.strip()]
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            out[k.strip()] = coerce_value(v.strip())
        else:
            out.setdefault("items", []).append(p)

    return out


def parse_metrics(lines: List[str]) -> Dict[str, Any]:
    """
    Joins continuation lines and parses:
      - cc algorithm token (leading bbr/cubic/etc)
      - key:value tokens
      - key value tokens
      - flags (single tokens)
      - name:(...) groups (bbr:(...), skmem:(...), etc)
    """
    text = " ".join([ln.strip() for ln in lines]).strip()
    metrics: Dict[str, Any] = {"raw": text}

    if not text:
        return metrics

    # Extract and remove name:(...) groups first
    paren_groups = {}
    for m in RE_PAREN_GROUP.finditer(text):
        name = m.group("name")
        body = m.group("body")
        paren_groups[name] = parse_paren_body(body)

    if paren_groups:
        metrics["groups"] = paren_groups
        # remove these groups from token stream so we do not double parse
        text_wo_groups = RE_PAREN_GROUP.sub("", text).strip()
    else:
        text_wo_groups = text

    tokens = [t for t in text_wo_groups.split() if t]

    # First token is often CC name (bbr, cubic, reno, bbr2, bbr3)
    if tokens and ":" not in tokens[0] and RE_IDENTIFIER.match(tokens[0]):
        metrics["cc"] = tokens[0]
        tokens = tokens[1:]

    i = 0
    while i < len(tokens):
        t = tokens[i]

        # key:value
        if ":" in t:
            k, v = t.split(":", 1)
            k = k.strip()
            v = v.strip()
            if k:
                metrics[k] = coerce_value(v)
            i += 1
            continue

        # key value form (send 123bps, pacing_rate 123bps, etc)
        if RE_IDENTIFIER.match(t) and (i + 1) < len(tokens):
            nxt = tokens[i + 1]
            # do not treat "wscale:..." style, already handled
            if ":" not in nxt:
                # if next token looks like a value, store as key value
                looks_like_value = bool(RE_FLOAT.match(nxt) or RE_NUM_UNIT.match(nxt) or RE_INT.match(nxt))
                if looks_like_value:
                    metrics[t] = coerce_value(nxt)
                    i += 2
                    continue

        # flags (app_limited, ecn, etc)
        if RE_IDENTIFIER.match(t):
            metrics.setdefault("flags", []).append(t)
        else:
            metrics.setdefault("unparsed", []).append(t)

        i += 1

    return metrics


def parse_ss_tin_output(ss_tin_output: str) -> Dict[str, Any]:
    blocks = split_blocks(ss_tin_output)
    sockets: List[Dict[str, Any]] = []

    for header, cont in blocks:
        if not header:
            continue

        m = RE_HEADER.match(header)
        if not m:
            sockets.append({"raw_header": header, "raw_cont": cont})
            continue

        state = m.group("state")
        recvq = int(m.group("recvq"))
        sendq = int(m.group("sendq"))
        local = m.group("local")
        peer = m.group("peer")
        proc = (m.group("proc") or "").strip()

        rec: Dict[str, Any] = {
            "state": state,
            "recv_q": recvq,
            "send_q": sendq,
            "local": parse_ip_port(local),
            "peer": parse_ip_port(peer),
            "process": proc,
            "header_raw": header,
            "metrics": parse_metrics(cont),
            "cont_lines_raw": cont,
        }
        sockets.append(rec)

    return {
        "meta": {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "hostname": pysocket.gethostname(),
            "source_cmd": "ss -tin",
        },
        "sockets": sockets,
    }


if __name__ == "__main__":
    # Example: replace this with your real variable
    ss_tin_output = subprocess.check_output(["ss", "-tin"], text=True)
    parse_ss_tin_output(ss_tin_output)
    raise SystemExit(
        "Import this file and call parse_ss_tin_output(ss_tin_output), "
        "or uncomment the subprocess line and run it as a script."
    )
