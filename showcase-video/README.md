# 一行で、ここまで。

「あなたの実力を見せつける最強の動画を作って」という一行の指示から作った 52 秒の動画。
完成品は [`out/showcase.mp4`](out/showcase.mp4)（1920×1080 / 30fps / 音あり）。

映像も音も、すべてコードで書いている。カメラ・編集ソフト・音源素材は使っていない。

## 構成（120BPM・1小節=60フレーム）

| フレーム | 場面 | 狙い |
| --- | --- | --- |
| 0–210 | 一行 | 静。黒に一行だけ。最後はカーソルへ突っ込む |
| 210–450 | 宣言 | 「カメラ 0台」「編集ソフト 0本」「全部、コードで書いた。」 |
| 450–630 | 01 数式 | 14,000 点を 球 → 結び目 → 波 へ変形 |
| 630–780 | 02 データ | 主役は数字ひとつ。グラフは根拠 |
| 780–960 | 03 実物 | このリポジトリのシフト管理表を実ブラウザで操作した画面 |
| 960–1080 | 04 音 | 流れている音の実データ（周波数帯・波形）を描画 |
| 1080–1380 | 見せ場 | 1秒の静寂 → 冒頭の一行が 42,000 粒になり「一行で、ここまで。」 |
| 1380–1560 | 次の一行 | 静。カーソルだけ残す |

強弱の設計: 見せ場は 1 箇所だけ。前後（冒頭・ブレイク・締め）は動かさない。

## 動画内の数字はすべて実測

- ソース行数 … `scripts/gen-stats.mjs` が実ファイルを数える
- サンプル数・タイピングのタイミング … `scripts/make-audio.mjs` が出力
- 「120セル入力 → 総労働 604:30h」 … `scripts/capture-app.cjs` が `../index.html` を実際に操作した結果
- 「前年比 108.1%」のグラフだけはサンプルデータ（画面内にも明記）

## 作り直し方

```bash
npm i
./scripts/fetch-fonts.sh        # フォント取得（初回のみ）
node scripts/capture-app.cjs    # シフト管理表の実画面を撮影（Playwright が必要）
node scripts/make-audio.mjs     # 音を合成 → public/soundtrack.wav
node scripts/gen-stats.mjs      # 行数などを集計
npx remotion render Showcase out/showcase.mp4 --crf=19 --jpeg-quality=92
```

プレビューは `npm run dev`（Remotion Studio）。
Chrome を自動取得できない環境では `REMOTION_BROWSER=/path/to/chrome-headless-shell` を指定する。

## 主なファイル

- `src/Composition.tsx` … 全体のタイムライン
- `src/scenes/*.tsx` … 各場面
- `src/lib/particles.ts` … 粒子の形と軌道（フレーム番号だけで決まる）
- `scripts/make-audio.mjs` … シンセ・ドラム・リバーブまで含む音の合成
