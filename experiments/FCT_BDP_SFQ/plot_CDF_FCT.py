#!/usr/bin/env python3

import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


def get_end_time(path: str, previous=None):
    text = Path(path).read_text().strip()

    i = text.rfind("\n{")
    i = 0 if i == -1 else i + 1

    data = json.loads(text[i:])
    try:
        return data["end"]["sum_sent"]["end"]
    except (KeyError, TypeError):
        return previous


def clean_numeric(values):
    cleaned = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if np.isnan(fv):
            continue
        cleaned.append(fv)
    return np.array(cleaned, dtype=float)


def cdf(values):
    arr = clean_numeric(values)
    if arr.size == 0:
        return np.array([]), np.array([])
    x = np.sort(arr)
    y = np.arange(1, len(x) + 1) / len(x)
    return x, y


def mean_std(values):
    arr = clean_numeric(values)
    if arr.size == 0:
        return np.nan, np.nan
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    return mu, sigma


def fit_fig_width_to_legend(fig, legend, pad_in=0.6, min_width_in=5.0):
    """
    Shrink/expand figure width so it roughly matches the legend width.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bbox_in = legend.get_window_extent(renderer=renderer).transformed(
        fig.dpi_scale_trans.inverted()
    )
    new_w = max(min_width_in, bbox_in.width + pad_in)
    w, h = fig.get_size_inches()
    if abs(new_w - w) > 0.05:
        fig.set_size_inches(new_w, h, forward=True)


def main():
    # Bigger fonts everywhere
    plt.rcParams.update({
        "font.size": 13,
        "axes.labelsize": 15,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "legend.fontsize": 9,
    })

    bdp_list = [0.1, 0.5, 1, 5, 10, 20]

    for bdp in bdp_list:
        prague, bbr3, cubic = [], [], []

        for i in range(1, 129):
            prague.append(get_end_time(f"{bdp}BDP/prague/hs{i}_out.json"))
            bbr3.append(get_end_time(f"{bdp}BDP/bbr/hs{i}_out.json"))
            cubic.append(get_end_time(f"{bdp}BDP/cubic/hs{i}_out.json"))

        x_p, y_p = cdf(prague)
        x_b, y_b = cdf(bbr3)
        x_c, y_c = cdf(cubic)

        mu_p, sig_p = mean_std(prague)
        mu_b, sig_b = mean_std(bbr3)
        mu_c, sig_c = mean_std(cubic)

        # Start with a reasonable size; we'll auto-adjust width to legend
        fig, ax = plt.subplots(figsize=(11, 5.5))

        # Labels (requested names)
        lbl_c = f"CUBIC\n$\\mu$ = {mu_c:.2f}\n$\\sigma$ = {sig_c:.2f}"
        lbl_b = f"BBRv3\n$\\mu$ = {mu_b:.2f}\n$\\sigma$ = {sig_b:.2f}"
        lbl_p = f"Prague\n$\\mu$ = {mu_p:.2f}\n$\\sigma$ = {sig_p:.2f}"

        # Plot order + requested colors
        ax.step(x_c, y_c, where="post", label=lbl_c, color="#2D72B7")
        ax.step(x_b, y_b, where="post", label=lbl_b, color="#82AA45")
        ax.step(x_p, y_p, where="post", label=lbl_p, color="#95253B")

        ax.set_xlim(0, 60)

        ax.set_xlabel("FCT [seconds]")
        ax.set_ylabel("CDF")
        ax.grid(True)

        # Legend above plot (same placement, now matches plot order)
        leg = ax.legend(
            loc="lower center",
            bbox_to_anchor=(0.5, 1.02),
            ncol=3,
            frameon=True,
            borderaxespad=0.2,
        )

        # Make figure width similar to legend width
        fit_fig_width_to_legend(fig, leg, pad_in=0.6, min_width_in=5.0)

        # Re-layout after resizing; reserve top space for legend
        fig.tight_layout(rect=[0, 0, 1, 0.86])

        fig.savefig(f"cdf_fct_{bdp}BDP_SFQ.pdf", bbox_inches="tight", pad_inches=0.12)
        plt.close(fig)


if __name__ == "__main__":
    main()