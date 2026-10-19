# packages/

| Package | Contents | State |
|---|---|---|
| `shared-types/openapi.json` | API contract generated from FastAPI (`scripts/export_openapi.py`) | Generated |
| `ui/` | Design tokens are currently in `apps/web/styles/globals.css` | Extract when a second frontend exists |
| `financial-schemas/` | Zod response schemas are currently in `apps/web/lib/schemas.ts` | Extract once they are generated from `openapi.json` |

The web app is not an npm workspace yet. `apps/web` installs its own dependencies, which keeps the
local install independent of the rest of the repo. Shared code moves here when a second consumer needs it.
Until then, keeping each module next to its only user avoids an untested build step.
