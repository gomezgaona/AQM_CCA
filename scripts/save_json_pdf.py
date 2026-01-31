#!/usr/bin/env python3
"""
Zip all .json files in ./results and move the zip to ./archived_experiments.

Run this on the h1 VM.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def find_base_dir(start: Path, max_up: int = 6) -> Path:
    """
    Find a directory (starting from `start` and walking up) that contains ./results.
    Falls back to `start` if not found.
    """
    cur = start.resolve()
    for _ in range(max_up + 1):
        if (cur / "results").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


def build_label(exp_name: str, num_flows: int, cc_name: str, buf_bdp: int) -> str:
    return f"{exp_name}_{num_flows}f_{cc_name}_{buf_bdp}bdp"


def unique_path(path: Path) -> Path:
    """
    If `path` exists, return a new path with _1, _2, ... appended before suffix.
    """
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    k = 1
    while True:
        candidate = path.with_name(f"{stem}_{k}{suffix}")
        if not candidate.exists():
            return candidate
        k += 1


def create_zip(results_dir: Path, label: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = unique_path(results_dir / f"{timestamp}_{label}.zip")

    json_files = sorted(results_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No .json files found in: {results_dir}")

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf:
        for f in json_files:
            zf.write(f, arcname=f.name)

    return zip_path


def move_to_archive(zip_path: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_path(archive_dir / zip_path.name)
    return zip_path.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive experiment JSON results into a zip.")
    parser.add_argument("--exp-name", default="preliminary", help="Experiment name label part")
    parser.add_argument("--num-flows", type=int, default=16, help="Number of flows label part")
    parser.add_argument("--cc-name", default="bbr3", help="Congestion control label part")
    parser.add_argument("--buf-bdp", type=int, default=32, help="Buffer in BDP label part")

    parser.add_argument(
        "--base-dir",
        default=None,
        help="Project base dir that contains results/. If omitted, auto-detect from current dir.",
    )
    args = parser.parse_args()

    start = Path(args.base_dir).expanduser() if args.base_dir else Path.cwd()
    base_dir = find_base_dir(start)

    results_dir = base_dir / "results"
    archive_dir = base_dir / "archived_experiments"

    if not results_dir.is_dir():
        raise FileNotFoundError(f"Results directory not found: {results_dir}")

    label = build_label(args.exp_name, args.num_flows, args.cc_name, args.buf_bdp)

    zip_path = create_zip(results_dir, label)
    archived_path = move_to_archive(zip_path, archive_dir)

    print(f"Archived zip: {archived_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
