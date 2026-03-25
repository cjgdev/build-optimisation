#!/usr/bin/env python3
"""Parse dot files from data/raw/dot/ into a clean edge table."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config
from build_optimiser.graph import load_graph


def main() -> None:
    cfg = load_config()
    raw_dir = Path(cfg["raw_data_dir"])
    processed_dir = Path(cfg["processed_data_dir"])
    processed_dir.mkdir(parents=True, exist_ok=True)

    dot_dir = raw_dir / "dot"
    if not dot_dir.exists() or not any(dot_dir.glob("*.dot")):
        print("Error: No dot files found. Run step 01 first.", file=sys.stderr)
        sys.exit(1)

    G = load_graph(str(dot_dir))

    edges = []
    for src, dst, data in G.edges(data=True):
        edges.append({
            "source_target": src,
            "dest_target": dst,
            "scope": data.get("scope", ""),
        })

    df = pd.DataFrame(edges)
    output_path = processed_dir / "edge_list.parquet"
    df.to_parquet(output_path, index=False)
    print(f"Wrote {len(df)} edges to {output_path}")


if __name__ == "__main__":
    main()
