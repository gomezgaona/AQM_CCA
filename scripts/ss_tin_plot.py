#!/usr/bin/env python3
import re
import time
import subprocess
from pathlib import Path

# -------------------- CONFIG --------------------
NUM_HOSTS   = 16
HOST_PREFIX = "hs"     # "hs" or "hr"
IPERF_PORT  = 5201     # set None to disable port filter
REFRESH_S   = 0.1
# -----------------------------------------------


# -------------------- LOCAL EXEC (quiet) --------------------
def exec_quiet(cmd_list):
    """
    Run a local command quietly and return stdout as text.
    """
    p = subprocess.run(
        cmd_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return p.stdout or ""


def _to_text(x):
    if isinstance(x, (tuple, list)):
        return "\n".join(str(p) for p in x if p is not None)
    return str(x)


# -------------------- PARSING HELPERS --------------------
def _find_int(text, key):
    m = re.search(rf"\b{key}:(\d+)\b", text)
    return int(m.group(1)) if m else None

def _find_float(text, key):
    m = re.search(rf"\b{key}:(\d+(?:\.\d+)?)\b", text)
    return float(m.group(1)) if m else None

def _find_rtt(text):
    m = re.search(r"\brtt:(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\b", text)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))

def _find_rate_bps(text, key):
    m = re.search(rf"\b{key}\s+(\d+)([KMG]?)bps\b", text)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    scale = {"": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}[unit]
    return val * scale

def _find_bbr_bw_bps(text):
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
    Returns a list of flow dicts for ESTAB sockets.
    Each socket is usually two lines: ESTAB header + tcp info.
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


# -------------------- SUMMARIZATION --------------------
def mean(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None

def sum_or_none(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None

def bps_to_mbps(x):
    return None if x is None else (x / 1e6)

def fmt_float(x, w=9, p=2):
    return f"{'-':>{w}}" if x is None else f"{x:>{w}.{p}f}"

def fmt_int(x, w=6):
    return f"{'-':>{w}}" if x is None else f"{int(x):>{w}}"

def fmt_bps(x, w=12):
    return f"{'-':>{w}}" if x is None else f"{x:>{w}.3e}"

def dominant_cc(ccs):
    ccs = [c for c in ccs if c]
    if not ccs:
        return "-"
    return max(set(ccs), key=ccs.count)

def summarize_host(flows, ack_rate_bps):
    send_bps = sum_or_none([f["send_bps"] for f in flows])
    pacing_bps = mean([f["pacing_bps"] for f in flows])
    delivery_bps = mean([f["delivery_bps"] for f in flows])
    bbr_bw_bps = mean([f["bbr_bw_bps"] for f in flows])

    return {
        "flows": len(flows),
        "cc": dominant_cc([f["cc"] for f in flows]),
        "avg_rtt": mean([f["rtt_ms"] for f in flows]),
        "min_rtt": mean([f["minrtt_ms"] for f in flows]),
        "avg_cwnd": mean([f["cwnd"] for f in flows]),
        "mss": mean([f["mss"] for f in flows]),
        "rto": mean([f["rto"] for f in flows]),
        "send_mbps": bps_to_mbps(send_bps),
        "send_bps": send_bps,
        "pacing_mbps": bps_to_mbps(pacing_bps),
        "pacing_bps": pacing_bps,
        "delivery_mbps": bps_to_mbps(delivery_bps),
        "delivery_bps": delivery_bps,
        "bbr_bw_mbps": bps_to_mbps(bbr_bw_bps),
        "bbr_bw_bps": bbr_bw_bps,
        "ack_mbps": bps_to_mbps(ack_rate_bps),
        "ack_bps": ack_rate_bps,
    }


# -------------------- TABLE OUTPUT --------------------
def clear_only_table():
    try:
        from IPython.display import clear_output
        clear_output(wait=True)
    except Exception:
        print("\033[2J\033[H", end="")

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


# -------------------- MININET NAMESPACE ACCESS --------------------
def pid_file_for(host):
    # Common locations across distros
    candidates = [
        Path("/var/run/mininet") / f"{host}.pid",
        Path("/run/mininet") / f"{host}.pid",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]

def ss_in_host_namespace(host):
    """
    Run: sudo mnexec -a <pid> ss -tin
    """
    pid_path = pid_file_for(host)
    try:
        pid = pid_path.read_text().strip()
    except FileNotFoundError:
        return ""

    if not pid:
        return ""

    cmd = ["sudo", "mnexec", "-a", pid, "ss", "-tin"]
    return exec_quiet(cmd)


# -------------------- MAIN MONITOR LOOP --------------------
def monitor_ss_table():
    prev_acked = {}  # host -> last total bytes_acked
    prev_time = {}   # host -> timestamp

    try:
        while True:
            rows = []
            now = time.time()

            for i in range(1, NUM_HOSTS + 1):
                host = f"{HOST_PREFIX}{i}"

                text = _to_text(ss_in_host_namespace(host))
                flows = parse_ss_tin_output(text, port_filter=IPERF_PORT)

                total_bytes_acked = sum_or_none([f["bytes_acked"] for f in flows]) or 0
                last_bytes = prev_acked.get(host, total_bytes_acked)
                last_t = prev_time.get(host, now)

                dt = max(1e-6, now - last_t)
                delta_bytes = max(0, total_bytes_acked - last_bytes)
                ack_rate_bps = (delta_bytes * 8.0) / dt

                prev_acked[host] = total_bytes_acked
                prev_time[host] = now

                summary = summarize_host(flows, ack_rate_bps)
                summary["host"] = host
                rows.append(summary)

            clear_only_table()
            print_table(rows)
            time.sleep(REFRESH_S)

    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    monitor_ss_table()
