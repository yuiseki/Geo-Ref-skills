---
name: document-maps
description: PDF、Word、PowerPoint、Excel の文書から、埋め込まれた画像を出どころ (ページ、ページ上の範囲、文書のハッシュ) 付きで取り出し、PDF のページを決まった dpi で画像に描く。文書の中の地図をジオリファレンスする前 (レベル 5) に使う。
---

# document-maps

文書の中の地図を合わせるには、まず地図の画像を文書から出す必要がある。どの画像が地図かは、このスキルでは決めない。後段のジオリファレンスの関門が、地図でない画像を拒否する。

## まず使うもの

文書 (PDF、docx、pptx、xlsx) や画像を 1 つ渡すと、地図かもしれない切り出しを、試す順に並べて書き出す。

```sh
uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with opencv-python-headless \
  python scripts/map_candidates.py report.pdf --out tmp/doc/cands
```

順番は次のとおり。

1. ページの一部に置かれた画像。大きい順。帯やタイルに分けて埋め込まれた画像はつないでから (`stitched`)、つないだ画像を部品より先に出す。
2. ページ全体を覆う画像 (スキャンしたページ、ページの背景) の中の、地図らしい矩形 (`rectangle`、ページごとに上位 3 つ)。続いてその画像の全体。
3. PDF だけ: 各ページを `--render-dpi` で描き、その中の地図らしい矩形 (`rendered`)。ベクタで描かれた地図のため。ページ全体の画像があるページは描き直さない。

画像 (png、jpg、tif など) を渡したときは、その中の矩形、続いて画像の全体。

`candidates.json` の各候補には、切り出しのファイル、画素の大きさ、ページ、dpi、ページ上の範囲 (`bbox_pt`、PDF の pt、原点は左下)、矩形の順位付けの値、出どころ (`from`: 種類、元の画像、元の画像の中の画素の範囲) が入る。分からないもの (Office の画像、画像ファイル、フォームの中の画像) の dpi と `bbox_pt` は書かない。

候補を後段 (place-hint とジオリファレンス) にこの順で渡し、受け入れられた最初の候補で止める。地図でない候補は登録に失敗し、関門が拒否する。

以下は、`map_candidates.py` が中で使っている個々の道具。

## 個々の道具

1. 埋め込まれた画像を全て取り出す。

   ```sh
   uvx --with pypdfium2==5.14.0 --with pillow python scripts/extract_images.py report.pdf --out tmp/doc/images
   ```

   `manifest.json` に、文書の SHA-256、pypdfium2 と pdfium の版、画像ごとのファイル、画素の大きさ、ページ (1 から)、ページ上の範囲 (PDF の pt、原点は左下) が入る。Office の文書 (docx、pptx、xlsx) では、zip の中のパス (`part`) が入る。

2. 帯やタイルに分けて埋め込まれた画像をつなぐ。

   ```sh
   uvx --with pillow python scripts/stitch_images.py tmp/doc/images/manifest.json
   ```

   同じページで、辺どうしが接し (隙間 0.5 pt と 1.5 画素以内)、解像度が同じ (各軸 2% 以内) で、接する辺の 9 割以上が重なる画像をまとめる。まとめた画像の合計の面積が外接する矩形を埋める (2% 以内) ときだけ、1 枚の PNG にする。`manifest.json` に `stitched` が足される。

3. ベクタで描かれた地図 (官公庁の PDF に多い) は画像として取れないので、ページを描く。

   ```sh
   uvx --with pypdfium2==5.14.0 --with pillow python scripts/render_pages.py report.pdf --out tmp/doc/pages --dpi 200
   ```

   dpi は結果と一緒に必ず記録する。画素が地上で何 m かは、dpi と印刷された縮尺が分かって初めて決まる。

4. 描いたページや、ページ全体の画像から、地図らしい矩形の候補を探す。

   ```sh
   uvx --with numpy --with opencv-python-headless python scripts/find_map_rectangles.py tmp/doc/pages/p001.png --out tmp/doc/cands
   ```

   紙の色と雑音は、ページの外周 (幅 2%) で測る。黄ばんだ紙のスキャンでも、白い紙と同じに扱える。候補は 3 種類あり、全て残す。
   - 紙の上のひとまとまりの領域 (`region`)
   - その領域の中で、半分以上塗られた 16 画素の升でできる最大の矩形 (`core`)。辺は画素の単位で詰め直す。地図に接した棒グラフ、見出し、凡例で領域が広がっても、この矩形は地図に留まる。
   - 長い直線で囲まれた枠 (`frame`、図郭)

   候補には、塗られている割合、色の数、線の向きの散らばり、上位 8 色が占める割合 (`palette`) と、それらの積の順位付けの値が付く。`palette` は、平らな塗りでできた地図と、濃淡が連続する写真を分ける (合成の絵とタイルの地図で、地図 0.77〜1.0、写真 0.36〜0.44)。値は並べ替えにだけ使い、候補を捨てない。

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
| `scripts/map_candidates.py` | 上の全てをまとめ、試す順に候補を書き出す。まず使うもの |
| `scripts/stitch_images.py` | 帯やタイルに分けて埋め込まれた画像をつなぐ |
| `scripts/find_map_rectangles.py` | ページの画像の中の、地図らしい矩形の候補と順位 |

テスト (文書はテストの中で作る):

```sh
uvx --with pypdfium2==5.14.0 --with pillow --with pytest pytest scripts/test_extract_images.py
uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with pytest pytest scripts/test_render_pages.py
uvx --with numpy --with opencv-python-headless --with pytest pytest scripts/test_find_map_rectangles.py
uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with pytest pytest scripts/test_stitch_images.py
uvx --with pypdfium2==5.14.0 --with pillow --with numpy --with opencv-python-headless --with pytest pytest scripts/test_map_candidates.py
```

## どこまで確かめたか (2026-11-04)

`evals/scripts/eval_find.py` で、ジオリファレンスもネットワークも使わずに、地図が候補の何番目に出るかを測った。レベル 1〜4 の課題の地図から一様に 60 枚を選び、合成の A4 文書 4 種類 (スキャン、黄ばんだ紙のスキャン、地図を 1 枚の画像で埋め込み、帯に分けて埋め込み) に置いた。正解の範囲と IoU 0.9 以上で重なった候補を当たりとした。

| 文書 | 1 番目が当たり (種 0 / 種 1) | 取りこぼし |
|---|---|---|
| スキャン | 58 / 58 | 2 / 2 |
| 黄ばんだ紙のスキャン | 59 / 58 | 1 / 2 |
| 画像で埋め込み | 60 / 60 | 0 / 0 |
| 帯に分けて埋め込み | 60 / 60 | 0 / 0 |

種 0 は、直しながら見た集合である。種 1 は、直した後に初めて流した。取りこぼしは全て、地が白い地図 (鉄道だけ、川だけ、e-paper) を、枠なしで白い紙に置いたものだった。線しか描かれていないので、地図の端が紙と区別できない。

直す前は、スキャンの 1 番目の当たりが 36/60 だった。地図に接した棒グラフで領域が広がったためで、`core` の候補で直した。

確かめていないこと:
- 実際の文書。合成の文書は、本文の行、棒グラフ、地図 1 枚だけでできている。写真、表、凡例、複数の地図の載ったページは、テストの合成の絵でしか見ていない。
- 傾いたスキャン。矩形は軸に沿ったものしか探さない。
- 白い地の地図を枠なしで置いたもの (上の取りこぼし)。
