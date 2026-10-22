"""Temporary script to inspect Excel schema. Run from backend/."""
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[2] / "data" / "raw" / "excel"
OUT = Path(__file__).resolve().parents[2] / "data" / "processed" / "excel_schema.json"


def inspect_file(path: Path) -> dict:
    df = pd.read_excel(path)
    sample = df.head(3).where(pd.notnull(df.head(3)), None)
    return {
        "file": path.name,
        "row_count": len(df),
        "columns": [str(c) for c in df.columns],
        "null_counts": {str(k): int(v) for k, v in df.isnull().sum().items()},
        "sample_rows": sample.to_dict(orient="records"),
    }


def main() -> None:
    results = [inspect_file(f) for f in sorted(BASE.glob("*.xlsx"))]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
