"""Builds reports for the 6 fake sessions made by make_demo_data.py (oldest first)."""
import subprocess, sys
from pathlib import Path
demo = Path(__file__).parent / "demo"
for f in sorted(demo.glob("bhav_*.csv")):
    tag = f.stem.split("_")[1]
    subprocess.run([sys.executable, "-m", "src.build_report", "--demo", "--bhav-file", str(f), "--hist-file", str(demo / "hist.csv"),
                    "--part-file", str(demo / f"part_{tag}.csv"), "--cash-file", str(demo / f"cash_{tag}.json"), "--force"],
                   check=True)
