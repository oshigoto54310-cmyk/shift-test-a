// リポジトリ直下の index.html（シフト管理表）を実ブラウザで起動し、
// 実際にプルダウンを操作してシフトを入力し、「入力前 / 入力後」の2枚を撮影する。
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "../..");
const out = path.resolve(__dirname, "../public");

const patterns = [
  ["A", "A", "公休", "B", "A", "A", "C", "公休", "A", "B"],
  ["B", "公休", "B", "B", "C", "公休", "A", "B", "B", "希望休"],
  ["C", "C", "A", "公休", "C", "E", "公休", "C", "有給", "C"],
  ["H", "公休", "H", "H", "公休", "H", "H", "G", "公休", "H"],
];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 2,
  });
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.goto("file://" + path.join(root, "index.html"));
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(out, "app-empty.png") });

  const perRow = await page.evaluate(
    () => document.querySelector("tbody tr")?.querySelectorAll("select.shift-select").length ?? 0,
  );
  let filled = 0;
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < perRow; c++) {
      const label = patterns[r][(c + r * 3) % patterns[r].length];
      // change のたびに表が再描画されるので、毎回 DOM から取り直す
      const ok = await page.evaluate(
        ({ r, c, label }) => {
          const row = document.querySelectorAll("tbody tr")[r];
          const el = row?.querySelectorAll("select.shift-select")[c];
          if (!el) return false;
          const opt = [...el.options].find((o) => o.textContent.trim() === label);
          if (!opt) return false;
          el.value = opt.value;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return true;
        },
        { r, c, label },
      );
      if (ok) filled++;
    }
  }
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(out, "app-filled.png") });
  const summary = await page.evaluate(
    () => document.body.innerText.match(/全スタッフ総労働[^\n]*/)?.[0] ?? null,
  );
  console.log(JSON.stringify({ perRow, filled, summary }));
  await browser.close();
})();
