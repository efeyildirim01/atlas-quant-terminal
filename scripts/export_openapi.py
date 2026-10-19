"""Write the API's OpenAPI document to packages/shared-types/openapi.json (the cross-app contract).

    cd apps/api && python ../../scripts/export_openapi.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("ATLAS_DATABASE_URL", "sqlite://")  # no DB access needed to build the schema

from app.main import create_app  # noqa: E402

out = Path(__file__).resolve().parents[1] / "packages" / "shared-types" / "openapi.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(out.parents[2])}")
