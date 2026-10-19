// Production build only when the web sources changed since the last build (used by baslat.cmd).
// Hashes every source file plus the build-relevant environment; the hash is stored inside the build folder,
// so deleting the folder also forces a rebuild.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const distDir = process.env.NEXT_DIST_DIR || ".next";
const stampFile = join(root, distDir, ".atlas-source-hash");
const SOURCES = ["app", "components", "features", "hooks", "lib", "styles", "public"];
const FILES = ["next.config.ts", "package-lock.json", "tsconfig.json", "postcss.config.mjs"];

function walk(dir, out) {
  if (!existsSync(dir)) return;
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
}

const files = [];
for (const d of SOURCES) walk(join(root, d), files);
for (const f of FILES) if (existsSync(join(root, f))) files.push(join(root, f));
files.sort();

const hash = createHash("sha256");
hash.update(`ATLAS_API_URL=${process.env.ATLAS_API_URL ?? ""}\n`);
for (const f of files) {
  hash.update(relative(root, f).replaceAll("\\", "/"));
  hash.update(readFileSync(f));
}
const digest = hash.digest("hex");

if (existsSync(stampFile) && readFileSync(stampFile, "utf8").trim() === digest) {
  console.log("     Web derlemesi guncel.");
  process.exit(0);
}

console.log("     Web derleniyor (kod degistigi icin, yaklasik 1 dakika)...");
const res = spawnSync(process.execPath, [join(root, "node_modules", "next", "dist", "bin", "next"), "build"], {
  cwd: root,
  stdio: ["ignore", "ignore", "inherit"],
  env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
});
if (res.status !== 0) {
  console.error("     Web derlemesi basarisiz.");
  process.exit(res.status ?? 1);
}
writeFileSync(stampFile, digest);
console.log("     Web derlendi.");
