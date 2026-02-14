import subprocess
import json
from pathlib import Path

from parse_ss_tin_output import parse_ss_tin_output
ss_tin_output = subprocess.check_output(["ss", "-tin"], text=True)

data = parse_ss_tin_output(ss_tin_output)

out = Path("ss_tin_snapshot.json")
out.write_text(json.dumps(data, indent=2), encoding="utf-8")

print(f"Saved {out} with {len(data['sockets'])} sockets")
