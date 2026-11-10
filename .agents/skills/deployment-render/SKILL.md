---
name: deployment-render
description: 部隊配置の GeoJSON を、NATO APP-6 の軍事記号 (Wikimedia Commons の SVG) で参照地図の上に描き、国連の配置図に似せた絵を作る。位置合わせと読み取りの結果を、目で確かめるための再現図。記号の出典と帰属表示を絵に書き込む。
---

# deployment-render

`deployment-geojson` が作った点を、規模の印と兵科の記号を付けた軍事記号にして、参照地図 (OSM のタイル) の上に置く。元の PDF の地図と並べて見比べると、読み取りと位置合わせが合っているかを、目で確かめられる。

## 使い方

記号の素材を Wikimedia Commons から取る (初回だけ。429 を避けて 1 件ごとに数秒待つので、数分かかる)。

```sh
python scripts/fetch_symbols.py --out symbols
```

参照地図は、`tile-reference` の `fetch_reference.py` などで、点の範囲より少し広く作っておく (`reference.png` と `reference.json`)。

```sh
uvx --with numpy --with opencv-python-headless --with cairosvg \
  python scripts/render_units.py deployment.geojson --reference ref_dir --symbols symbols --out out.jpg
```

cairosvg は、システムの cairo のライブラリを読む (Linux は libcairo2、macOS は Homebrew の cairo)。macOS では、uv が入れた Python が Homebrew の `/opt/homebrew/lib` を探さず、`DYLD_FALLBACK_LIBRARY_PATH` も SIP に消されて、`no library called "cairo" was found` で落ちる。Homebrew の Python を使わせれば通る (2026-11-10、別の macOS の環境で `test_render_units.py` の 7 件が通った)。

```sh
UV_PYTHON=/opt/homebrew/bin/python3.12 uvx --with numpy --with opencv-python-headless --with cairosvg --with pytest pytest scripts/test_render_units.py
```

## 描き方

- 兵科の記号は Commons の APP-6 の枠と絵 (歩兵、医療、工兵、通信、憲兵、砲兵、航空、司令部)。素材が無い兵科 (軍事監視員、FPU、IPO など) は、枠の中に略称を書く。国連の図でもそう書く。
- 規模は枠の上に描く (小隊は点 3 つ、中隊は棒 1 本、大隊は棒 2 本、旅団は x、師団は x 2 つ)。
- 同じ場所に積んだ記号は、点から出した引き出し線の先に並べる。国名の札は枠の下。
- 点の位置は GeoJSON の経緯度で、引き出し線の根元が正確な位置になる。記号の箱の位置は正確でない。

## 時系列の GIF

同じ参照地図の上に、日付順の GeoJSON を 1 コマずつ重ねて GIF にする。参照地図は、全てのファイルの点が入る範囲で 1 枚作る (コマごとに範囲が変わると、動かない部隊が動いて見える)。同じ日付が 2 つあれば先の 1 つを使う。コマには日付と描いた部隊の数を書き、地図全体の答えが関門を通らなかったコマには、その印を付ける。

```sh
uvx --with numpy --with opencv-python-headless --with cairosvg --with pillow \
  python scripts/make_gif.py a.geojson b.geojson ... --reference ref_dir --symbols symbols --out series.gif
```

コマの日付は PDF の作成日で、地図が表す日付ではない。部隊数の増減には、実際の変化と、位置の取りこぼし (位置が決まらなかった部隊は描かれない) が混ざる。

## 素材の扱い

Commons の APP-6 の記号の多くは CC BY-SA 4.0 (作者 CdnMCG)。このリポジトリには素材を入れない。絵には、作者とライセンスと Commons の URL、地図の出典 (Based on United Nations map、© OpenStreetMap contributors)、無保証の注意を書き込む。この絵を公開するときは、CC BY-SA 4.0 の条件 (表示と継承) に従う。

## 限界

- 描くのは GeoJSON にある点だけ。位置が決まらなかった記号は描かれないので、元の図より少ない。
- 記号は APP-6 の絵で、国連軍事記号ハンドブックの絵とは細部が違う (航空など)。
