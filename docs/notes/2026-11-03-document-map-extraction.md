# 文書から地図の画像を取り出す: markitdown を使うか、自前で作るか (2026-11-03)

## 欲しいもの

PDF、PowerPoint、Word、Excel の中にある、地図らしい矩形を、画像として取り出す。Markdown は要らない。後段 (レベル 5) で、取り出した画像をジオリファレンスする。

## markitdown で確かめたこと

https://github.com/microsoft/markitdown (MIT License)。読んだ版は commit `7482c09` (2026-10-22)。

- 目的は、文書を LLM に渡すための Markdown にすること。出力は Markdown の文字列。
- PDF (`_pdf_converter.py`): pdfminer.six と pdfplumber で文字を取るだけで、画像を扱うコードが無い。PDF の中の地図は取り出せない。
- Word (`_docx_converter.py`): mammoth で HTML にし、そこから Markdown にする。埋め込み画像は、変換器を継承して `_image_to_html` を上書きしたときだけ、画像のストリームを受け取れる。
- PowerPoint (`_pptx_converter.py`): python-pptx で図形をたどり、画像には alt テキストか LLM の説明 (`_llm_caption.py`) を付ける。画像のバイト列は、同じく上書きの口から受け取れる。
- Excel (`_xlsx_converter.py`): pandas と openpyxl で表を Markdown にする。画像は上書きの口から、シートの表の後ろに並ぶ。
- どの形式でも、ページやスライドの上の位置と大きさは、出力に出ない。

## 自前で作る場合に確かめたこと

- PDF: pypdfium2 5.14.0 (BSD-3-Clause と Apache-2.0)。手元の論文の PDF (12 ページ) で、画像オブジェクト 62 個を、画素の大きさとページ上の範囲付きで取り出せた。ページ全体を任意の倍率で描ける。注意として、フォーム XObject の中の画像は、範囲がページでなくフォームの座標で返った ([0, 0, 618, 303] など)。ページ上の位置が要るときは、行列を合成する。
- PyMuPDF は AGPL なので使わない。
- Office (docx、pptx、xlsx): 中身は zip で、画像は `word/media/`、`ppt/media/`、`xl/media/` にそのまま入っている。標準ライブラリの zipfile で取り出せる。スライドやページの上の位置と大きさは、描画の XML (`wp:extent`、`a:xfrm`) にある。この形式での取り出しは、まだ実際のファイルで試していない (未確認)。
- 古い形式 (.doc、.ppt、.xls) と、Office の中のベクタの図 (EMF、WMF) は、LibreOffice で変換する必要がある (未確認)。

## 判断

自前で作るのがよいと考える。理由は 4 つ。

1. 一番多いと思われる PDF で、markitdown は画像を取り出さない。
2. 欲しいのは画像と、その位置 (ページ、範囲)。markitdown は Markdown の文字列を返し、位置を捨てる。
3. Office の画像は、zip から直接取れる。markitdown の上書きの口を通すより短く、依存も少ない (markitdown は mammoth、pandas、openpyxl、python-pptx、pdfminer.six、pdfplumber と、LLM の説明の仕組みを持ち込む)。
4. このリポジトリの方針 (判断を LLM に任せない) と、markitdown の画像の説明 (LLM) は合わない。

markitdown が役に立ちそうなのは、文書の文字から地名を取り、place-hint の手がかりにするときくらい。これも python-pptx や pdfminer で足りる見込み。

## 自前の道具の形 (案)

- `extract_images`: 文書から、埋め込まれたラスタ画像を、出どころ (ファイル、ページかスライド、範囲) 付きで全て取り出す。PDF は pypdfium2、Office は zipfile。
- `render_pages`: PDF のページを画像に描く。ベクタで描かれた地図 (官公庁の PDF に多い) は、画像オブジェクトとしては取れないため。
- `find_map_rectangles`: 描いたページの中から、地図らしい矩形の候補を探す。古典的な手がかりで行う: 長い直線で囲まれた矩形 (図郭)、矩形の中のエッジの密度と向きの散らばり、地図に多い色 (水の青、緑地の緑)。候補は取りこぼさないことを優先する。
- 本当に地図かどうかは、後段のジオリファレンスの関門で決まる。地図でない画像は、参照の地図に合わずに失敗を宣言するはず。これを陰性の対照で確かめる。

まだ決めていないこと: 地図らしさの判定をどこまで道具に持たせるか (候補を多めに出して後段で落とすか、前で絞るか)。
