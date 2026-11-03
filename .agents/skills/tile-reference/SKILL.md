---
name: tile-reference
description: 経緯度の枠とズームから、ラスタの XYZ タイルをつないで、EPSG:3857 の geotransform 付きの参照画像を作る。地図の画像を合わせる先 (参照) が要るときに使う。
---

# tile-reference

地図の画像を地上の座標に結び付けるには、座標の分かっている参照の画像が要る。このスキルは、タイル配信 (既定は https://tile.yuiseki.net/styles) のラスタタイルをつないで、参照の画像を作る。

## 手順

1. 合わせたい地図がありうる範囲 (経緯度の枠、西 南 東 北の順) と、ズームを決める。手がかり (hint.json) があれば、その `bbox` と `zoom` を使う。
2. 参照の画像を作る。

   ```sh
   uvx --with numpy --with pillow python scripts/fetch_reference.py --style osm-liberty --zoom 15 \
     --bbox 139.70 35.66 139.79 35.71 --cache tmp/tiles --out tmp/ref
   ```

3. `tmp/ref/reference.png` と `tmp/ref/reference.json` ができる。`geotransform` は GDAL の 6 つの数で、参照の画素 (列, 行) から EPSG:3857 のメートルへ写す。画素 (0, 0) は左上の画素の左上の角。

## 気を付けること

- 枠は、西 南 東 北の順。経度と緯度を取り違えると、範囲の検査で止まる。
- タイル配信は、キャッシュに無いタイルを描くのに 1 枚数秒から 30 秒近くかかる (2026-11-03 に tile.yuiseki.net で測った)。取ったタイルは `--cache` に残り、2 回目からは取りに行かない。並列で大量に取らない。必要なタイルが `--max-tiles` (既定 400) を超えたら止まる。枠を狭めるか、ズームを下げる。
- 取れないタイル (404、PNG でない、大きさが違う) は、白で埋めずにエラーにする。
- `--offline` は、キャッシュにあるタイルだけで作る。
- Web メルカトルの外 (緯度 85.0511 度を超える、経度 180 度を超える) は扱えない。
- スタイルの一覧は https://tile.yuiseki.net/styles.json 。

## スクリプト

| スクリプト | 役割 |
|---|---|
| `scripts/webmercator.py` | 経緯度、タイルの全体の画素、EPSG:3857 のメートルの間の換算 |
| `scripts/tiles.py` | タイルの取得とキャッシュ、つなぎ合わせ |
| `scripts/fetch_reference.py` | 参照の画像と geotransform を書き出す |

テスト:

```sh
uvx --with numpy --with pyproj --with pytest pytest scripts/test_webmercator.py
uvx --with numpy --with pillow --with pytest pytest scripts/test_tiles.py scripts/test_fetch_reference.py
```

`webmercator.py` は pyproj の EPSG:3857 と、高緯度を含めて照合している。タイルのつなぎ方は、位置を色に埋めた合成のタイルで、1 画素ずつ確かめている。実際のタイルを取るテストは `GEOREF_NETWORK=1` のときだけ流れる。
