---
name: feature-registration
description: 地図の画像と、座標の分かった参照の画像の間で、局所特徴 (SIFT、ORB) を対応させ、幾何的に食い違わない対応を GCP (地上の基準点) にする。地図の画像と参照の画像の見た目が近いとき (同じスタイルの地図など) に使う。
---

# feature-registration

画像の中の目立つ点 (特徴点) を両方の画像で見つけ、似た点どうしを組にする。組のうち、1 つの射影変換で説明できるものだけを残し (MAGSAC)、それを GCP にする。どの点が正しい組かを、自分の目で決めない。

## 手順

1. 参照の画像 (`reference.png` と、EPSG:3857 の geotransform を書いた `reference.json`) を用意する。
2. 対応を取り、答えの JSON を書く。

   ```sh
   uvx --with numpy --with opencv-python-headless python scripts/register.py image.png tmp/ref --out answer.json
   ```

3. 終了コードが 1 なら、対応が足りず、答えは `"status": "failed"` になっている。推測の答えで埋めない。理由は `reason` に書いてある。
4. 答えを返す前に、関門 (GCP の数、広がり、leave-one-out の残差、変換の形、手がかりの枠) を通す。

## 答えの形

```json
{"status": "ok", "image": {"width": 900, "height": 700}, "method": "projective", "crs": "EPSG:4326",
 "gcps": [{"col": 12.5, "row": 40.5, "lon": 139.71, "lat": 35.70}, ...]}
```

`col` と `row` は地図の画像の画素の座標で、(0, 0) は左上の画素の左上の角。OpenCV の特徴点の座標は画素の中心が整数なので、0.5 を足してある。GCP は、画像を 10 x 10 に分けた升ごとに最大 4 点に間引き、一部に偏らないようにしてある。

## 使える条件と、使えない条件

- 前提: 地図の画像と参照の画像が、同じ描き方 (色、線、文字) をしていて、1 つの射影変換でおおよそ重なる。レベル 1 (同じスタイル) はこれに当たる。
- 違うスタイルの地図 (色や線の太さが違う)、要素を絞った地図 (川や鉄道だけ)、紙のよれのような非線形の歪みでは、前提が崩れる。崩れたら失敗を記録し、別の道具を作る。
- 札幌のような碁盤の目では、似た交差点が繰り返すので、取り違えた対応が多数派になりうる。
- 検出器は SIFT (既定、位置がサブ画素) と ORB (位置が画素単位)。OpenCV 5.0.0 には AKAZE が無い。
- 合成の画像で測った GCP の誤差 (2026-11-03): SIFT は中央値 0.5 画素未満、ORB は中央値 0.57、最大 2.55 画素。

## スクリプト

| スクリプト | 役割 |
|---|---|
| `scripts/register.py` | 特徴の対応、MAGSAC、GCP の間引きと書き出し |
| `scripts/webmercator.py` | EPSG:3857 のメートルから経緯度への換算 |

テスト:

```sh
uvx --with numpy --with opencv-python-headless --with pytest pytest scripts/test_register.py
uvx --with numpy --with pyproj --with pytest pytest scripts/test_webmercator.py
```

合成の地図らしい画像に既知の射影変換を掛け、GCP が真の位置から何画素ずれるかを測っている。関係の無い画像では、失敗を宣言することも確かめている。
