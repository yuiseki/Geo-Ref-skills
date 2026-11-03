---
name: gcp-refinement
description: GCP の集合から、leave-one-out の残差が大きい点を 1 点ずつ除き、除いた点と理由を答えに記録する。除く割合には上限がある。GCP が数十点以上あり、関門の leave-one-out の残差で落ちたとき、関門の前に使う。
---

# gcp-refinement

自動で作った GCP には、取り違えた対応や、位置の雑音の大きい点が混じる。点が数百あると、雑音の分布の端だけで、leave-one-out の残差の最大が大きくなる。このスキルは、残差の最大の点を 1 点ずつ除き、除くたびに残差を計算し直す (Bahgat と Runfola 2021 の手順に近い。彼らは除いて最も良くなる点を探すが、ここでは計算を軽くするため、残差の最大の点を除く)。

## 手順

1. 答えの JSON (GCP、方法、画像の大きさ) を用意する。
2. 精錬する。

   ```sh
   uvx --with numpy python scripts/refine_gcps.py answer.json --out refined.json
   ```

3. 出力の `refinement` を読む。`stopped` が `target_met` なら目標 (既定 3 画素) を満たした。`max_remove_fraction` なら、除く割合の上限 (既定 10%) に達しても目標に届かなかった。
4. 精錬した答えを、関門に通す。関門は、記録された除いた割合も確かめる。

## 気を付けること

- 残差が合うまで点を除くことは、上限と記録があるときだけ安全。上限が無いと、どんな答えも関門を通ってしまう。上限を上げて通すことを、最初の手にしない。
- 上限に達したら、それは「多くの点が 1 つの変換で説明できない」という印。位置の取り違え、方法の次数の不足、地図の非線形の歪みを疑う。
- 除いた点は、`refinement.removed` に元の番号と残差と一緒に残る。黙って捨てない。
- GCP が十数点しかないときは、1 点を除くだけで割合が大きくなる。点を増やすほうを先に考える。

## 確かめたこと (2026-11-03)

- 60 点に 3 点の外れ値を混ぜた合成の例で、その 3 点だけを除いた。
- 1 画素の雑音の 300 点では、雑音だけで最大が 3 画素を超え、5% 以下を除いて目標を満たした。
- 3 分の 1 の点が別の場所を指す例では、上限 (10%) で止まり、目標を満たさなかった。
- 除くたびに残差を計算し直すこと、上限を、それぞれ外すとテストが落ちる。

## スクリプト

| スクリプト | 役割 |
|---|---|
| `scripts/refine_gcps.py` | 1 点ずつの除去と記録 |
| `scripts/transforms.py` | 変換の当てはめと leave-one-out |
| `scripts/webmercator.py` | 経緯度と EPSG:3857 の換算 |

テスト:

```sh
uvx --with numpy --with pytest pytest scripts/test_refine_gcps.py
uvx --with numpy --with scikit-image --with pytest pytest scripts/test_transforms.py
uvx --with numpy --with pyproj --with pytest pytest scripts/test_webmercator.py
```
