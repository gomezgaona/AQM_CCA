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


def get_retx_and_bytes(path: str, previous=(None, None)):
    """
    Returns (retransmits, bytes) from:
      data["end"]["sum_sent"]["retransmits"]
      data["end"]["sum_sent"]["bytes"]
    for the *last* JSON object.
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
        ss = data["end"]["sum_sent"]
        # Explicitly use the exact fields you specified
        return ss["retransmits"], ss["bytes"]
    except (KeyError, TypeError, AttributeError):
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

    # Build retransmission-% matrix: rows=BDP, cols=CCA
    retx_pct = np.full((len(bdp_list), len(ccas)), np.nan, dtype=float)

    # Approximate TCP segments from bytes using MSS (adjust if you want)
    MSS_BYTES = 1460.0

    for r, bdp in enumerate(bdp_list):
        for c, (cca_dir, _) in enumerate(ccas):
            total_retx = 0.0
            total_bytes = 0.0

            for i in range(1, 129):
                path = f"{bdp}BDP/{cca_dir}/hs{i}_out.json"
                retx, byt = get_retx_and_bytes(path)

                if retx is None or byt is None:
                    continue

                try:
                    total_retx += float(retx)
                    total_bytes += float(byt)
                except (TypeError, ValueError):
                    continue

            if total_bytes > 0:
                est_segments = total_bytes / MSS_BYTES
                retx_pct[r, c] = (total_retx / est_segments) * 100.0 if est_segments > 0 else np.nan

    # Plot heatmap
    fig, ax = plt.subplots(figsize=(7.5, 4.5))

    # ---- ROBUST "NUMERIC + EXPLICIT MASK + VISIBLE BAD" FIX ----
    retx_pct_num = np.array(retx_pct, dtype=float)
    mask = ~np.isfinite(retx_pct_num)

    vmax = float(np.nanmax(retx_pct_num)) if np.isfinite(np.nanmax(retx_pct_num)) else 1.0
    vmax = max(vmax, 0.1)

    cmap = plt.get_cmap("RdYlGn_r").copy()
    cmap.set_bad(color="lightgray")

    im = ax.imshow(
        np.ma.array(retx_pct_num, mask=mask),
        aspect="auto",
        cmap=cmap,
        vmin=0.0,
        vmax=vmax,
        origin="lower",
        interpolation="nearest",
        alpha=1.0,
    )
    # ------------------------------------------------------------

    # Ticks/labels
    ax.set_xticks(np.arange(len(ccas)))
    ax.set_xticklabels([lbl for _, lbl in ccas])
    ax.set_yticks(np.arange(len(bdp_list)))
    ax.set_yticklabels([f"{bdp}" for bdp in bdp_list])

    #ax.set_xlabel("Congestion control algorithm")
    ax.set_ylabel("Buffer Size [BDP]")

    # Cell annotations
    for rr in range(retx_pct_num.shape[0]):
        for cc in range(retx_pct_num.shape[1]):
            v = retx_pct_num[rr, cc]
            txt = "NA" if not np.isfinite(v) else f"{v:.2f}"
            ax.text(cc, rr, txt, ha="center", va="center", fontsize=10)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Retransmissions [%]")

    fig.tight_layout()
    fig.savefig("heatmap_retransmissions.pdf", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


if __name__ == "__main__":
    main()