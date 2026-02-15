#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy as np

BDP_VALUES_DEFAULT = [0.1, 0.5, 1, 5, 10, 20]
X_TICKS_LOG = [0.1, 0.5, 1, 5, 10, 20]


def fmt_bdp(bdp: float) -> str:
    return f"{bdp:g}"


def extract_fct_seconds(filename: Path) -> float:
    with filename.open() as f:
        data = json.load(f)

    end = data.get("end", {})

    for key in ("sum_received", "sum_sent", "sum"):
        sec = end.get(key, {}).get("seconds", None)
        if sec is not None:
            return float(sec)

    streams = end.get("streams", [])
    secs: list[float] = []
    for st in streams:
        for side in ("receiver", "sender"):
            sec = st.get(side, {}).get("seconds", None)
            if sec is not None:
                secs.append(float(sec))
    if secs:
        return float(max(secs))

    raise KeyError(f"Could not find FCT seconds in iperf3 JSON: {filename}")


def setup_plot(font_size: int = 12):
    import matplotlib.pyplot as plt

    # Avoid "Font family 'normal' not found."
    font = {"family": "sans-serif", "weight": "normal", "size": font_size}
    matplotlib.rc("font", **font)

    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    ax.grid(True, which="both", lw=0.3, linestyle=(0, (1, 10)))
    return fig, ax, plt


def find_cca_results_dir(data_root: Path, bdp: float, cca_dir: str) -> Path:
    # <data_root>/<BDP>BDP/<CCA>/
    d = data_root / f"{fmt_bdp(bdp)}BDP" / cca_dir
    if d.is_dir():
        return d
    raise FileNotFoundError(f"CCA results dir not found for BDP={fmt_bdp(bdp)} at: {d}")


def find_algo_results_dir(data_root: Path, bdp: float, algo_dir: str) -> Path:
    """
    For BBR/CUBIC/etc:
      <data_root>/<BDP>BDP/<algo_dir>/
    Also accept:
      <data_root>/<BDP>BDP/<algo_dir>/results/
      <data_root>/<BDP>/<algo_dir>/
      <data_root>/<BDP>/<algo_dir>/results/
    """
    b = fmt_bdp(bdp)
    candidates = [
        data_root / f"{b}BDP" / algo_dir,
        data_root / f"{b}BDP" / algo_dir / "results",
        data_root / b / algo_dir,
        data_root / b / algo_dir / "results",
    ]
    for c in candidates:
        if c.is_dir():
            return c

    raise FileNotFoundError(
        f"{algo_dir.upper()} results dir not found for BDP={b}. Tried:\n  " + "\n  ".join(str(c) for c in candidates)
    )


def load_fcts_fixed(results_dir: Path, num_flows: int, host_prefix: str) -> list[float]:
    # hs1_out.json .. hsN_out.json
    fcts: list[float] = []
    missing: list[str] = []
    bad: list[str] = []

    for i in range(1, num_flows + 1):
        f = results_dir / f"{host_prefix}{i}_out.json"
        if not f.exists():
            missing.append(f.name)
            continue
        try:
            fcts.append(extract_fct_seconds(f))
        except Exception:
            bad.append(f.name)

    if missing:
        print(f"Warning: missing {len(missing)} files in {results_dir}. Example: {missing[0]}")
    if bad:
        print(f"Warning: {len(bad)} files could not be parsed in {results_dir}. Example: {bad[0]}")
    if not fcts:
        raise FileNotFoundError(
            f"No usable iperf3 JSON files found in: {results_dir} "
            f"(expected {host_prefix}1_out.json .. {host_prefix}{num_flows}_out.json)"
        )
    return fcts


def load_fcts_glob_robust(results_dir: Path, host_prefix: str) -> tuple[list[float], int]:
    """
    For BBR/CUBIC dirs: file naming might differ. We try:
      1) hs*_out.json
      2) *.json
      3) recursively **/*.json
    Returns (parsed_fcts, matched_file_count_for_pattern_used).
    """
    patterns = [f"{host_prefix}*_out.json", "*.json"]
    files: list[Path] = []
    for pat in patterns:
        files = sorted(results_dir.glob(pat))
        if files:
            break

    if not files:
        files = sorted(results_dir.rglob("*.json"))

    if not files:
        return ([], 0)

    fcts: list[float] = []
    bad = 0
    for f in files:
        try:
            fcts.append(extract_fct_seconds(f))
        except Exception:
            bad += 1

    if bad:
        print(f"Warning: {bad} JSON files could not be parsed in {results_dir}")

    return (fcts, len(files))


def build_out_name(cca_dir: str) -> str:
    today = datetime.now().strftime("%Y%m%d")
    return f"{today}_fct_vs_bdp_mean_{cca_dir}_bbr_cubic.pdf"


def plot_series(ax, x: list[float], y: list[float], label: str, z: int):
    mask = np.isfinite(np.asarray(y, dtype=float))
    if mask.any():
        xs = [x[i] for i in range(len(x)) if mask[i]]
        ys = [y[i] for i in range(len(y)) if mask[i]]
        ax.plot(xs, ys, linewidth=2, marker="o", label=label, zorder=z)
    else:
        print(f"Warning: No finite values to plot for {label}.")


def main() -> int:
    p = argparse.ArgumentParser(description="Plot mean FCT per BDP for <CCA>, BBR, and CUBIC flows.")
    p.add_argument("--num-flows", type=int, default=16)
    p.add_argument("--host-prefix", default="hs")
    p.add_argument("--bdp-values", nargs="*", type=float, default=BDP_VALUES_DEFAULT)
    p.add_argument("--cca-dir", default="prague")
    p.add_argument("--data-root", default=".")
    p.add_argument("--plots-dir", default="plots")
    p.add_argument("--plots-absolute", action="store_true")
    p.add_argument("--no-show", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.no_show:
        matplotlib.use("Agg")

    script_dir = Path(__file__).resolve().parent
    data_root_raw = Path(args.data_root).expanduser()
    data_root = data_root_raw if data_root_raw.is_absolute() else (script_dir / data_root_raw)
    data_root = data_root.resolve()
    if not data_root.is_dir():
        raise FileNotFoundError(f"Data root not found: {data_root}")

    x: list[float] = []
    y_cca: list[float] = []
    y_bbr: list[float] = []
    y_cubic: list[float] = []

    for bdp in args.bdp_values:
        x.append(float(bdp))

        # CCA mean (e.g., prague) fixed 16 flows
        cca_dir = find_cca_results_dir(data_root, bdp, args.cca_dir)
        fcts_cca = load_fcts_fixed(cca_dir, args.num_flows, args.host_prefix)
        mean_cca = float(np.mean(np.asarray(fcts_cca, dtype=float)))
        y_cca.append(mean_cca)

        # BBR mean from <data_root>/<BDP>BDP/bbr[/results]/
        try:
            bbr_dir = find_algo_results_dir(data_root, bdp, "bbr")
            fcts_bbr, matched_bbr = load_fcts_glob_robust(bbr_dir, args.host_prefix)
            mean_bbr = float(np.mean(np.asarray(fcts_bbr, dtype=float))) if fcts_bbr else float("nan")
            if args.verbose:
                print(
                    f"BDP={fmt_bdp(bdp)}  BBR dir={bbr_dir}  matched_files={matched_bbr}  parsed_fcts={len(fcts_bbr)}"
                )
        except FileNotFoundError as e:
            mean_bbr = float("nan")
            if args.verbose:
                print(f"BDP={fmt_bdp(bdp)}  BBR missing: {e}")
        y_bbr.append(mean_bbr)

        # CUBIC mean from <data_root>/<BDP>BDP/cubic[/results]/
        try:
            cubic_dir = find_algo_results_dir(data_root, bdp, "cubic")
            fcts_cubic, matched_cubic = load_fcts_glob_robust(cubic_dir, args.host_prefix)
            mean_cubic = float(np.mean(np.asarray(fcts_cubic, dtype=float))) if fcts_cubic else float("nan")
            if args.verbose:
                print(
                    f"BDP={fmt_bdp(bdp)}  CUBIC dir={cubic_dir}  matched_files={matched_cubic}  parsed_fcts={len(fcts_cubic)}"
                )
        except FileNotFoundError as e:
            mean_cubic = float("nan")
            if args.verbose:
                print(f"BDP={fmt_bdp(bdp)}  CUBIC missing: {e}")
        y_cubic.append(mean_cubic)

        bbr_str = "NA" if not np.isfinite(mean_bbr) else f"{mean_bbr:.6f}s"
        cubic_str = "NA" if not np.isfinite(mean_cubic) else f"{mean_cubic:.6f}s"
        print(f"BDP={fmt_bdp(bdp)}  {args.cca_dir}_mean={mean_cca:.6f}s  bbr_mean={bbr_str}  cubic_mean={cubic_str}")

    fig, ax, plt = setup_plot()

    plot_series(ax, x, y_cca, label=f"{args.cca_dir} (mean)", z=3)
    plot_series(ax, x, y_bbr, label="BBR (mean)", z=4)
    plot_series(ax, x, y_cubic, label="CUBIC (mean)", z=5)

    ax.set_xlabel("Buffer Size [BDP]")
    ax.set_ylabel("Average Flow Completion Time [s]")
    ax.legend(loc="best")

    # Log x-axis with ONLY these ticks and padded limits
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(matplotlib.ticker.FixedLocator(X_TICKS_LOG))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%g"))
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xlim(0.08, 25)

    if args.plots_absolute:
        plots_dir = (Path.cwd() / args.plots-dir).resolve()  # noqa: F821
    else:
        plots_dir = (data_root / args.plots_dir).resolve()
    plots_dir.mkdir(parents=True, exist_ok=True)

    out_pdf = plots_dir / build_out_name(args.cca_dir)
    fig.savefig(out_pdf, bbox_inches="tight")

    if not args.no_show:
        plt.show()
    plt.close(fig)

    print(f"Saved PDF: {out_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
