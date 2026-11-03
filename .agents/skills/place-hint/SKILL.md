---
name: place-hint
description: 地図の画像に書かれた地名を tesseract で読み、自前の Nominatim で引いて、地図がどのあたりかの手がかり (経緯度の枠) を作る。場所の分からない地図を合わせる前に使う。文字の無い地図には使えない。
---

# place-hint

地図を参照の画像に合わせるには、だいたいの場所が要る。場所が分からないときは、地図に書かれた地名から、あたりを付ける。地名の意味を自分で解釈して場所を決めない。読み取りと検索と集計は、このスキルのスクリプトで行う。

## 手順

1. 手がかりを作る。

   ```sh
   uvx --with numpy --with opencv-python-headless python scripts/place_hint.py image.png --out place_hint.json \
     --countrycodes jp --cache tmp/nominatim
   ```

2. 終了コードが 0 なら、`place_hint.json` の `bbox` (西 南 東 北) が手がかりの枠。`support` が、枠を支えた地名。1 なら、支えが足りず、失敗の宣言 (`status: failed`)。推測の枠を作らない。
3. 枠を、参照の画像を作るときの範囲に使う。ズームは別に決める (地図の縮尺は、このスキルでは分からない)。

## 中身

1. 文字を読む (`ocr_words.py`)。画像を 3 倍に拡大し、-45 度から 45 度まで 15 度ごとに回して読む。地図は回っていることがあり、tesseract は水平な文字しか読めない (19 度回った大阪の地図で、回さずに読めた地名は 1、回し戻すと 15 だった)。tesseract の疎な読み取りは日本語を 1 文字ずつ返すので、同じ行で接する文字をつないで、名前の候補にもする。
2. 名前らしいものだけを残す (`clean_name`)。ラテン文字は 4 文字以上で、大文字か頭文字だけ大文字。CHOME、STATION のような一般語と、その切れ端 (HOME) は除く。日本語は漢字を含む 2 文字以上。
3. 自前の Nominatim (https://nominatim.yuiseki.net/) で引く (`nominatim.py`)。公開の nominatim.openstreetmap.org は呼ばない。Python の既定の User-Agent は 403 で断られるので、道具の名前を名乗る。1 件ずつ、間を空けて呼び、答えは `--cache` に残す。
4. Nominatim は緩く当てる (DORI で Showa-dori avenue が出る)。名前の表記 (name、name:en、name:ja-Latn など) のどれかが、読んだ名前と一致する答えだけを残す。大文字小文字、ハイフン、空白、長音の記号の違いは無視する (`norm`)。
5. 名前ごとの候補のうち、半径 10 km の中に最も多くの名前がそろう場所を選ぶ。名前の重みは、候補の数の逆数 (CHUO、KITA のようにどこにでもある名前は軽い)。3 つ以上の名前、重みの合計 1.5 以上がそろわなければ、失敗を宣言する。枠は、そろった名前の範囲に 4 km の余白を足したもの。

## 使えない条件と、確かめたこと (2026-11-03)

- 文字の無い地図 (川、鉄道だけ) では使えない。
- 畑のように文字が少なく小さい地図 (十勝、旭川の郊外、z15 の osm-liberty) では、地名を 1 つも読めず、失敗を宣言した。
- 切れ端の名前 (DORI、HOME、ASHI) で大阪の地図を 4 度東に置いたことがある。表記の一致を求めて直した。
- どこにでもある名前 (CHUO、HIGASHI、KITA) で札幌の地図を 7 度ずれた所に置いたことがある。重みを候補の数の逆数にして直した。
- 枠の余白が 2 km では、場所は合っていても地図の範囲がはみ出すことがあった (金沢)。地名は地図の中ほどに集まりやすいため。
- 上の 3 つは、同じ 6 課題を見ながら直したので、効果は別の課題で測る (`evals/scripts/eval_place_hint.py`)。

## スクリプト

| スクリプト | 役割 |
|---|---|
| `scripts/ocr_words.py` | tesseract の呼び出し、回転、日本語の文字のつなぎ |
| `scripts/nominatim.py` | 自前の Nominatim の呼び出しとキャッシュ |
| `scripts/place_hint.py` | 名前の選別、表記の一致、集まりの検出、枠 |

テスト:

```sh
uvx --with pytest pytest scripts/test_place_hint.py scripts/test_nominatim.py
uvx --with numpy --with opencv-python-headless --with pytest pytest scripts/test_ocr_words.py
```

tesseract の無い環境では、`test_ocr_words.py` の読み取りのテストは飛ばされる。実際の Nominatim を呼ぶテストは `GEOREF_NETWORK=1` のときだけ流れる。
