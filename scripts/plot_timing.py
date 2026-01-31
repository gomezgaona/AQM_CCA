#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np


def find_base_dir(start: Path, max_up: int = 6) -> Path:
    cur = start.resolve()
    for _ in range(max_up + 1):
        if (cur / "results").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


def extract_iperf_timing(filename: Path) -> list[float]:
    """
    Return throughput per second from iperf3 JSON (Gbps).
    Returns [] if intervals are missing or empty.
    """
    with filename.open() as f:
        data = json.load(f)

    intervals = data.get("intervals", [])
    out = []
    for it in intervals:
        s = it.get("sum", {})
        bps = s.get("bits_per_second", None)
        if bps is None:
            continue
        out.append(float(bps) / 1e9)
    return out


def setup_plot(font_size: int = 12):
    font = {"family": "normal", "weight": "normal", "size": font_size}
    matplotlib.rc("font", **font)
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(14, 8))
    fig.subplots_adjust(hspace=0.1)
    for ax in axes:
        ax.grid(True, which="both", lw=0.3, linestyle=(0, (1, 10)))
    return fig, axes


def calculate_fairness(th_per_flow: list[list[float]]) -> list[float]:
    th = np.asarray(th_per_flow, dtype=float)
    m, _ = th.shape
    sum_x = th.sum(axis=0)
    sum_x2 = (th**2).sum(axis=0)
    denom = m * sum_x2
    fairness = np.where(denom == 0, 100.0, 100.0 * (sum_x**2) / denom)
    return fairness.tolist()


def build_pdf_name(exp_name: str, num_flows: int, cc_name: str, buf_bdp: int) -> str:
    today = datetime.now().strftime("%Y%m%d")
    return f"{today}_{exp_name}_{num_flows}f_{cc_name}_{buf_bdp}bdp.pdf"


def plot_results(throughput: list[float], th_per_flow: list[list[float]], out_path: Path, show: bool):
    if not throughput:
        raise ValueError("Nothing to plot: aggregate throughput series is empty (N == 0).")

    fairness = calculate_fairness(th_per_flow)
    fig, axes = setup_plot()

    N = len(throughput)
    t = list(range(N))

    axes[0].plot(t, fairness, linewidth=2, marker="o", label="Fairness")
    axes[1].plot(t, throughput, linewidth=2, marker="o", label="Agg. Tput")

    for flow_id, flow_series in enumerate(th_per_flow):
        axes[2].plot(t, flow_series[:N], linewidth=1.5, marker="o", label=f"Flow {flow_id + 1}")

    axes[0].set_ylabel("Fairness [%]")
    axes[1].set_ylabel("Throughput [Gbps]")
    axes[2].set_ylabel("Throughput [Gbps]")
    axes[2].set_xlabel("Time [seconds]")

    axes[0].legend(loc="lower right")
    axes[1].legend(loc="upper right")

    num_flows = len(th_per_flow)
    items_per_col = 2
    ncol = max(1, math.ceil(num_flows / items_per_col))
    axes[2].legend(loc="upper right", ncol=ncol, fontsize=10, frameon=True)

    axes[0].set_ylim([0, 105])

    max_agg = float(np.max(np.asarray(throughput, dtype=float)))
    axes[1].set_ylim(0, max_agg + 5)

    max_flow = float(np.max(np.asarray(th_per_flow, dtype=float)))
    axes[2].set_ylim(0, max_flow + 5)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")

    if show:
        plt.show()

    plt.close(fig)
    print(f"Saved PDF: {out_path.resolve()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot iperf3 throughput and fairness from results/*.json")
    parser.add_argument("--num-hosts", type=int, default=16)
    parser.add_argument("--host-prefix", default="hs")
    parser.add_argument("--exp-name", default="preliminary")
    parser.add_argument("--cc-name", default="bbr3")
    parser.add_argument("--buf-bdp", type=int, default=32)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--plots-dir", default="plots")
    parser.add_argument("--no-show", action="store_true")
    args = parser.parse_args()

    if args.no_show:
        matplotlib.use("Agg")

    start = Path(args.base_dir).expanduser() if args.base_dir else Path.cwd()
    base_dir = find_base_dir(start)

    results_dir = (base_dir / args.results_dir).resolve()
    plots_dir = (base_dir / args.plots_dir).resolve()

    if not results_dir.is_dir():
        raise FileNotFoundError(f"Results directory not found: {results_dir}")

    th_per_flow: list[list[float]] = []
    missing = []
    empty = []

    for i in range(1, args.num_hosts + 1):
        f = results_dir / f"{args.host_prefix}{i}_out.json"
        if not f.exists():
            missing.append(f.name)
            continue

        series = extract_iperf_timing(f)
        if len(series) == 0:
            empty.append(f.name)
            continue

        th_per_flow.append(series)

    if missing:
        print(f"Warning: missing {len(missing)} files (skipped). Example: {missing[0]}")
    if empty:
        print(f"Warning: {len(empty)} files had 0 intervals (skipped). Example: {empty[0]}")

    if not th_per_flow:
        raise FileNotFoundError(
            f"No usable iperf3 timing series found in {results_dir}. "
            f"Check that your hs*_out.json files contain non-empty 'intervals'."
        )

    N = min(len(x) for x in th_per_flow)
    if N <= 0:
        raise ValueError(
            "All remaining flows have 0 samples after trimming. "
            "At least one flow likely has no 'intervals' samples."
        )

    th_per_flow = [x[:N] for x in th_per_flow]

    agg_th = [float(sum(flow[t] for flow in th_per_flow)) for t in range(N)]

    out_pdf = plots_dir / build_pdf_name(args.exp_name, len(th_per_flow), args.cc_name, args.buf_bdp)
    plot_results(agg_th, th_per_flow, out_pdf, show=(not args.no_show))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
