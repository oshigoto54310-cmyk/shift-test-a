// 動画内に出す「事実」を実ファイルから数える。数字を手で書かないためのスクリプト。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const walk = (dir) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "generated" ? [] : walk(p);
    return /\.(tsx?|mjs|cjs)$/.test(e.name) ? [p] : [];
  });

const files = [...walk(path.join(root, "src")), ...walk(path.join(root, "scripts"))];
const lines = files.reduce((n, f) => n + (fs.readFileSync(f, "utf8").match(/\n/g) ?? []).length, 0);

// 背景に流すコード片（見せ場の粒子まわり）
const pick = ["src/scenes/Climax.tsx", "src/lib/particles.ts"];
const snippet = pick
  .flatMap((f) => fs.readFileSync(path.join(root, f), "utf8").split("\n"))
  .filter((l) => l.trim().length > 0 && !l.trim().startsWith("import"))
  .map((l) => l.replace(/\t/g, "  ").slice(0, 64));

fs.writeFileSync(path.join(root, "src/generated/stats.json"), JSON.stringify({ lines, files: files.length, snippet }, null, 1));
console.log(JSON.stringify({ lines, files: files.length, snippetLines: snippet.length }));
