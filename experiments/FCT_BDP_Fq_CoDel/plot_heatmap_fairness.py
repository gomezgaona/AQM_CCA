#!/usr/bin/env python3

import json
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


def get_bits_per_second(path: str, previous=None):
    """
    Returns data["end"]["sum_sent"]["bits_per_second"] from the *last* JSON object
    in the file (iperf3 JSON can have extra output before the final JSON).
    """
    try:
        text = Path(path).read_text().strip()
    except FileNotFoundError:
        return previous

    i = text.rfind("\n{")
    i = 0 if i == -1 else i + 1

    try:
        data = json.loads(text[i:])
    except json.JSONDecodeError:
        return previous

    try:
        return data["end"]["sum_sent"]["bits_per_second"]
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
        if np.isnan(fv) or np.isinf(fv):
            continue
        cleaned.append(fv)
    return np.array(cleaned, dtype=float)


def jain_fairness(values):
    """
    Jain's fairness index:
        J = (sum(x)^2) / (n * sum(x^2)),  0..1
    """
    x = clean_numeric(values)
    n = x.size
    if n == 0:
        return np.nan
    denom = n * np.sum(x * x)
    if denom == 0:
        return np.nan
    return float((np.sum(x) ** 2) / denom)


def main():
    # BDPs on Y axis
    bdp_list = [0.1, 0.5, 1, 5, 10, 20]

    # CCAs on X axis (order + labels you’ve been using)
    ccas = [
        ("cubic", "CUBIC"),
        ("bbr", "BBRv3"),
        ("prague", "Prague"),
    ]

    # Build fairness matrix: rows=BDP, cols=CCA
    fairness = np.full((len(bdp_list), len(ccas)), np.nan, dtype=float)

    for r, bdp in enumerate(bdp_list):
        for c, (cca_dir, _) in enumerate(ccas):
            bps_values = []
            for i in range(1, 129):
                path = f"{bdp}BDP/{cca_dir}/hs{i}_out.json"
                bps_values.append(get_bits_per_second(path))
            fairness[r, c] = jain_fairness(bps_values)

    # Plot heatmap
    fig, ax = plt.subplots(figsize=(7.5, 4.5))

    masked = np.ma.masked_invalid(fairness)
    im = ax.imshow(masked, aspect="auto", cmap="RdYlGn", vmin=0.0, vmax=1.0, origin="lower")

    # Ticks/labels
    ax.set_xticks(np.arange(len(ccas)))
    ax.set_xticklabels([lbl for _, lbl in ccas])
    ax.set_yticks(np.arange(len(bdp_list)))
    ax.set_yticklabels([f"{bdp}" for bdp in bdp_list])

    #ax.set_xlabel("Congestion control algorithm")
    ax.set_ylabel("Buffer Size [BDP]")

    # Cell annotations
    for r in range(fairness.shape[0]):
        for c in range(fairness.shape[1]):
            v = fairness[r, c]
            txt = "NA" if np.isnan(v) else f"{v:.3f}"
            ax.text(c, r, txt, ha="center", va="center", fontsize=10)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Fairness index")

    fig.tight_layout()
    fig.savefig("heatmap_fairness.pdf", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


if __name__ == "__main__":
    main()