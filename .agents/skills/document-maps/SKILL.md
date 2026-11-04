---
name: document-maps
description: PDF、Word、PowerPoint、Excel の文書から、埋め込まれた画像を出どころ (ページ、ページ上の範囲、文書のハッシュ) 付きで取り出し、PDF のページを決まった dpi で画像に描く。文書の中の地図をジオリファレンスする前 (レベル 5) に使う。
---

# document-maps

文書の中の地図を合わせるには、まず地図の画像を文書から出す必要がある。どの画像が地図かは、このスキルでは決めない。後段のジオリファレンスの関門が、地図でない画像を拒否する。

## 手順

1. 埋め込まれた画像を全て取り出す。

   ```sh
   uvx --with pypdfium2==5.14.0 --with pillow python scripts/extract_images.py report.pdf --out tmp/doc/images
   ```

   `manifest.json` に、文書の SHA-256、pypdfium2 と pdfium の版、画像ごとのファイル、画素の大きさ、ページ (1 から)、ページ上の範囲 (PDF の pt、原点は左下) が入る。Office の文書 (docx、pptx、xlsx) では、zip の中のパス (`part`) が入る。

2. ベクタで描かれた地図 (官公庁の PDF に多い) は画像として取れないので、ページを描く。

   ```sh
   uvx --with pypdfium2==5.14.0 --with pillow python scripts/render_pages.py report.pdf --out tmp/doc/pages --dpi 200
   ```

   dpi は結果と一緒に必ず記録する。画素が地上で何 m かは、dpi と印刷された縮尺が分かって初めて決まる。

3. 取り出した画像や描いたページを、場所の手がかり (place-hint) とジオリファレンスの道具に渡す。

## 使えない条件 (2026-11-04)

- フォーム XObject の中の画像は、ページ上の範囲を出さない (`in_form: true`)。pdfium がフォームの座標で範囲を返すため。行列の合成はまだ作っていない。
- Office の文書で、画像がスライドやページのどこに置かれているか (`wp:extent`、`a:xfrm`) は、まだ読んでいない。
- 古い形式 (doc、ppt、xls) と、Office の中のベクタの図 (EMF、WMF) は扱わない。LibreOffice で PDF にしてからページを描く (未確認)。
- 大きなページを高い dpi で描くと、画像が大きくなる (A1 の 400 dpi で約 13,000 x 9,000 画素)。dpi は地図の線が読める最小にし、高くするときはプロセスのメモリに上限を掛ける。
- 規約で転載や二次利用が禁じられた文書は、取り出した画像も含めて、リポジトリの外に置く。公開する成果物には、数えた数字だけを載せる。

## スクリプト

| スクリプト | 役割 |
|---|---|
| `scripts/extract_images.py` | 埋め込まれた画像と、出どころの記録 |
| `scripts/render_pages.py` | PDF のページを決まった dpi で描く。PDF の pt から画素への換算 (`pt_to_px`) |

テスト (文書はテストの中で作る):

```sh
uvx --with pypdfium2==5.14.0 --with pillow --with pytest pytest scripts/test_extract_images.py
uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with pytest pytest scripts/test_render_pages.py
```
