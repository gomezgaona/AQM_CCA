#!/usr/bin/env python3
"""
Terminal monitor (JupyterHub Terminal on FABRIC):
Shows a refreshed table (only output) summarizing `ss -tin` for each Mininet host.

It runs commands like:
  mininet/util/m hs1 ss -tin

Stop with Ctrl+C
"""

import re
import time
import subprocess

# -------------------- CONFIG (hardcode here) --------------------
NUM_HOSTS   = 16
HOST_PREFIX = "hs"          # "hs" or "hr"
IPERF_PORT  = 5201          # set to None to disable port filtering
REFRESH_S   = 0.1

MN_M_CMD    = "mininet/util/m"   # path to Mininet "m" helper
USE_SUDO    = False              # set True if `m` requires sudo
# ---------------------------------------------------------------


# -------------------- Command runner --------------------
def run_cmd(cmd: str) -> str:
    """Run a shell command and return stdout (no extra prints)."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return p.stdout or ""
    except Exception:
        return ""


# -------------------- Parsing helpers --------------------
def _find_int(text, key):
    m = re.search(rf"\b{key}:(\d+)\b", text)
    return int(m.group(1)) if m else None

def _find_float(text, key):
    m = re.search(rf"\b{key}:(\d+(?:\.\d+)?)\b", text)
    return float(m.group(1)) if m else None

def _find_rtt(text):
    # rtt:22.876/10.763
    m = re.search(r"\brtt:(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\b", text)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))

def _find_rate_bps(text, key):
    # send 8988984bps, pacing_rate 22604480bps, delivery_rate 794488bps
    m = re.search(rf"\b{key}\s+(\d+)([KMG]?)bps\b", text)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    scale = {"": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}[unit]
    return val * scale

def _find_bbr_bw_bps(text):
    # bbr:(bw:793952bps,mrtt:14.379,...)
    m = re.search(r"bbr:\(.*?\bbw:(\d+)([KMG]?)bps", text)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    scale = {"": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}[unit]
    return val * scale

def _extract_ipport_tokens(header_line):
    parts = header_line.split()
    return [p for p in parts if ":" in p and re.search(r":\d+$", p)]

def _keep_port(src, dst, port):
    if port is None:
        return True
    return (src and src.endswith(f":{port}")) or (dst and dst.endswith(f":{port}"))


def parse_ss_tin_output(ss_text, port_filter=None):
    """
    Parse `ss -tin` output into a list of per-flow dicts.
    Each flow appears as:
      line i   : ESTAB ...
      line i+1 : tcp info (bbr/cubic ... rtt:.. cwnd:.. send ... pacing_rate ... delivery_rate ...)
    """
    lines = [ln.strip() for ln in ss_text.splitlines() if ln.strip()]
    flows = []
    i = 0

    while i < len(lines):
        if not lines[i].startswith("ESTAB"):
            i += 1
            continue

        header = lines[i]
        info = lines[i + 1] if i + 1 < len(lines) else ""

        ipports = _extract_ipport_tokens(header)
        src = ipports[0] if len(ipports) >= 1 else None
        dst = ipports[1] if len(ipports) >= 2 else None

        if not _keep_port(src, dst, port_filter):
            i += 2
            continue

        tokens = info.split()
        cc = tokens[0] if tokens else None

        rtt_ms, _ = _find_rtt(info)

        flows.append({
            "src": src,
            "dst": dst,
            "cc": cc,
            "rtt_ms": rtt_ms,
            "minrtt_ms": _find_float(info, "minrtt"),
            "cwnd": _find_int(info, "cwnd"),
            "mss": _find_int(info, "mss"),
            "rto": _find_int(info, "rto"),
            "bytes_acked": _find_int(info, "bytes_acked"),
            "send_bps": _find_rate_bps(info, "send"),
            "pacing_bps": _find_rate_bps(info, "pacing_rate"),
            "delivery_bps": _find_rate_bps(info, "delivery_rate"),
            "bbr_bw_bps": _find_bbr_bw_bps(info),
        })

        i += 2

    return flows


# -------------------- Summaries + formatting --------------------
def mean(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None

def sum_or_none(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None

def dominant_cc(ccs):
    ccs = [c for c in ccs if c]
    return max(set(ccs), key=ccs.count) if ccs else "-"

def bps_to_mbps(x):
    return None if x is None else (x / 1e6)

def fmt_float(x, w=9, p=2):
    return f"{'-':>{w}}" if x is None else f"{x:>{w}.{p}f}"

def fmt_int(x, w=6):
    return f"{'-':>{w}}" if x is None else f"{int(x):>{w}}"

def fmt_bps(x, w=12):
    return f"{'-':>{w}}" if x is None else f"{x:>{w}.3e}"


def summarize_host(flows, ack_rate_bps):
    send_bps    = sum_or_none([f["send_bps"] for f in flows])
    pacing_bps  = mean([f["pacing_bps"] for f in flows])
    delivery_bps= mean([f["delivery_bps"] for f in flows])
    bbr_bw_bps  = mean([f["bbr_bw_bps"] for f in flows])

    return {
        "flows": len(flows),
        "cc": dominant_cc([f["cc"] for f in flows]),
        "avg_rtt": mean([f["rtt_ms"] for f in flows]),
        "min_rtt": mean([f["minrtt_ms"] for f in flows]),
        "avg_cwnd": mean([f["cwnd"] for f in flows]),
        "mss": mean([f["mss"] for f in flows]),
        "rto": mean([f["rto"] for f in flows]),

        # Outgoing (from ss)
        "send_mbps": bps_to_mbps(send_bps),
        "send_bps": send_bps,
        "pacing_mbps": bps_to_mbps(pacing_bps),
        "delivery_mbps": bps_to_mbps(delivery_bps),
        "bbr_bw_mbps": bps_to_mbps(bbr_bw_bps),

        # Incoming-ish (ACK progress): Δbytes_acked/Δt * 8
        "ack_mbps": bps_to_mbps(ack_rate_bps),
        "ack_bps": ack_rate_bps,
    }


# -------------------- Terminal table (only output) --------------------
def clear_screen():
    print("\033[2J\033[H", end="")  # ANSI clear + home

def print_table(rows):
    header = (
        f"{'Host':<5} {'#F':>3} {'CC':<5} "
        f"{'RTT':>7} {'minRTT':>7} {'cwnd':>6} {'MSS':>5} {'RTO':>5} "
        f"{'Send(M)':>9} {'Send(bps)':>12} "
        f"{'ACK(M)':>9} {'ACK(bps)':>12} "
        f"{'Pace(M)':>9} {'Del(M)':>9} {'BBRbw(M)':>9}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['host']:<5} {r['flows']:>3} {r['cc']:<5} "
            f"{fmt_float(r['avg_rtt'],7,2)} {fmt_float(r['min_rtt'],7,2)} "
            f"{fmt_float(r['avg_cwnd'],6,1)} {fmt_int(r['mss'],5)} {fmt_float(r['rto'],5,0)} "
            f"{fmt_float(r['send_mbps'],9,2)} {fmt_bps(r['send_bps'],12)} "
            f"{fmt_float(r['ack_mbps'],9,2)} {fmt_bps(r['ack_bps'],12)} "
            f"{fmt_float(r['pacing_mbps'],9,2)} {fmt_float(r['delivery_mbps'],9,2)} {fmt_float(r['bbr_bw_mbps'],9,2)}"
        )


# -------------------- Main loop --------------------
def monitor():
    prev_acked = {}  # host -> last total bytes_acked
    prev_time  = {}  # host -> timestamp

    while True:
        rows = []
        now = time.time()

        for i in range(1, NUM_HOSTS + 1):
            host = f"{HOST_PREFIX}{i}"

            sudo = "sudo " if USE_SUDO else ""
            cmd = f"{sudo}{MN_M_CMD} {host} ss -tin"
            ss_text = run_cmd(cmd)

            flows = parse_ss_tin_output(ss_text, port_filter=IPERF_PORT)

            # ACK progress rate (bits/s)
            total_bytes_acked = sum_or_none([f["bytes_acked"] for f in flows]) or 0
            last_bytes = prev_acked.get(host, total_bytes_acked)
            last_t = prev_time.get(host, now)

            dt = max(1e-6, now - last_t)
            delta_bytes = max(0, total_bytes_acked - last_bytes)
            ack_rate_bps = (delta_bytes * 8.0) / dt

            prev_acked[host] = total_bytes_acked
            prev_time[host] = now

            s = summarize_host(flows, ack_rate_bps)
            s["host"] = host
            rows.append(s)

        clear_screen()
        print_table(rows)
        time.sleep(REFRESH_S)


if __name__ == "__main__":
    try:
        monitor()
    except KeyboardInterrupt:
        pass
