#!/usr/bin/env bash
set -euo pipefail

# copy_results_to_tree.sh
#
# Copies iperf3 JSON results into:
#   <DATA_ROOT>/<BDP>/<CCA>/
#
# Defaults (portable):
#   DATA_ROOT = directory where this script lives (recommended: experiments/FCT_BDP)
#   SRC_DIR   = first existing of:
#                1) <script_dir>/results
#                2) ./results
#                3) /home/ubuntu/results
#
# Destination directory must already exist.

usage() {
  cat <<'EOF'
Usage:
  copy_results_to_tree.sh <BDP> <CCA> [--src <SRC_DIR>] [--data-root <DATA_ROOT>]

Examples:
  ./copy_results_to_tree.sh 1BDP prague
  ./copy_results_to_tree.sh 0.1BDP prague --src /home/ubuntu/results
  ./copy_results_to_tree.sh 10BDP cubic --data-root /path/to/experiments/FCT_BDP

Notes:
  - Destination must exist: <DATA_ROOT>/<BDP>/<CCA>/
EOF
}

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

BDP="$1"
CCA="$2"
shift 2

# Where is this script located?
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults
DATA_ROOT="$SCRIPT_DIR"
SRC_DIR=""

# Parse optional flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --src)
      [[ $# -ge 2 ]] || { echo "Error: --src requires a value"; exit 1; }
      SRC_DIR="$2"
      shift 2
      ;;
    --data-root)
      [[ $# -ge 2 ]] || { echo "Error: --data-root requires a value"; exit 1; }
      DATA_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

# Validate BDP format: number + "BDP"
if [[ ! "$BDP" =~ ^[0-9]+([.][0-9]+)?BDP$ ]]; then
  echo "Error: <BDP> must look like 0.1BDP, 1BDP, 10BDP, etc. Got: '$BDP'"
  exit 1
fi

# If --src not provided, auto-detect a sensible default
if [[ -z "$SRC_DIR" ]]; then
  if [[ -d "$SCRIPT_DIR/results" ]]; then
    SRC_DIR="$SCRIPT_DIR/results"
  elif [[ -d "./results" ]]; then
    SRC_DIR="./results"
  elif [[ -d "/home/ubuntu/results" ]]; then
    SRC_DIR="/home/ubuntu/results"
  else
    echo "Error: Could not find a default source results directory."
    echo "Tried: '$SCRIPT_DIR/results', './results', '/home/ubuntu/results'"
    echo "Fix: pass --src /path/to/results"
    exit 1
  fi
fi

# Resolve to absolute paths
SRC_ABS="$(realpath -m "$SRC_DIR")"
ROOT_ABS="$(realpath -m "$DATA_ROOT")"
DST_DIR="${ROOT_ABS}/${BDP}/${CCA}"

if [[ ! -d "$SRC_ABS" ]]; then
  echo "Error: Source directory does not exist: $SRC_ABS"
  echo "Fix: pass --src /path/to/results"
  exit 1
fi

if [[ ! -d "$DST_DIR" ]]; then
  echo "Error: Destination directory must exist: $DST_DIR"
  echo "Create it first, e.g.: mkdir -p \"$DST_DIR\""
  exit 1
fi

shopt -s nullglob
files=( "$SRC_ABS"/* )
shopt -u nullglob

if (( ${#files[@]} == 0 )); then
  echo "Error: No files found in $SRC_ABS"
  exit 1
fi

cp -av "$SRC_ABS"/. "$DST_DIR"/
echo "Done. Copied contents of $SRC_ABS to $DST_DIR"
