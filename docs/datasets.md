# データ

## 本番用に取っておくデータ: AI4CMA の map georeferencing challenge

- 名前: Training and validation data from the AI for Critical Mineral Assessment Competition (ver. 2.0, July 2025)
- 所在: https://www.sciencebase.gov/catalog/item/63a100d6d34e0de3a1f2794f 。ジオリファレンスの課題は子のアイテム https://www.sciencebase.gov/catalog/item/64c14e4fd34e70357a32990f (Map georeferencing challenge training and validation data)。
- 引用: Goldman, M.A., Rosera, J.M., Lederer, G.W., Graham, G.E., Mishra, A., and Yepremyan, A., 2023, Training and validation data from the AI for Critical Mineral Assessment Competition (ver. 2.0, July 2025): U.S. Geological Survey data release, https://doi.org/10.5066/P9FXSPT1 。競技の振り返りは Goldman ほか (2025)、Applied Computing and Geosciences v. 27, 100274, https://doi.org/10.1016/j.acags.2025.100274 。
- 中身: USGS と DARPA が 2022 年に開いた競技の、スキャンした地質図などの地図と、その GCP (正解)。地図は既刊の出版物から作られ、出典は `MapGeoreferencingReferences.csv` にある。
- ファイル (2026-11-03 に ScienceBase の目録で確かめた大きさ):

  | ファイル | 大きさ |
  |---|---:|
  | `Training.tar.gz` | 85.1 GB |
  | `Validation.tar.gz` | 34.2 GB |
  | `map-georeferencing-challenge-eval-data.tar.gz` | 2.83 GB |
  | `map-georeferencing-challenge-eval-clues.zip` | 27.6 KB |
  | `validation_clues.tar.gz` | 6.6 KB |
  | `AI4CMA_Map Georeferencing Challenge_Validation Answer Key.zip` | 150 KB |
  | `AI4CMA_Map_Georeferencing_Challenge_Evaluation_Answer_Key.zip` | 65 KB |
  | `Georeferencing Challenge Details.pdf` | 1.4 MB |
  | `AI4CMA_Georeferencing_Challenge_Baseline.ipynb` | 22 KB |
  | `MapGeoreferencingReferences.csv` | 311 KB |

- 利用の条件: FGDC の metadata (`ai4cma_data_GEO.xml`) の `accconst` は None、`useconst` は免責の文だけ。USGS のデータリリースだが、地図の画像そのものが既刊の出版物に由来するので、画像の再配布の条件は未確認。このリポジトリには画像も正解も入れない。
- 未確認: clues の中身 (どんな手がかりが渡されるか)、正解の GCP の形式と CRS、地図の枚数。

### 取っておく理由と扱い

信頼できる実データで、正解を持つ。スキルと関門の最後の確かめに使う。

- スキルを直すために、このデータの結果を読まない。読んで直したら、読んだ地図は評価として汚れたものとし、どれを読んだかを記録する。
- 開発と、失敗からのスキルの更新は、下の模擬のデータ (tile.yuiseki.net から作るレベル 1〜5) で行う。
- Training は大きいので、必要になったら、Validation と eval の小さい側から取る。

## 開発に使うデータ: tile.yuiseki.net のラスタタイル

- 所在: https://tile.yuiseki.net/ (TileServer GL、作者のセルフホスト)。Cloudflare の後ろにある。
- ラスタの XYZ は `https://tile.yuiseki.net/styles/<style>/{z}/{x}/{y}.png` (256 px) と `.../styles/<style>/512/{z}/{x}/{y}.png` (512 px)。スタイルの一覧は `https://tile.yuiseki.net/styles.json`。
- 2026-11-03 に、東京の z14 のタイル (x=14552, y=6451) を取って確かめたこと:
  - 取れたスタイル: `osm-liberty`、`osm-liberty-no-text`、`osm-carto`、`osm-bright`、`osm-fiord`、`railways`、`rivers`、`roads-minimal`、`e-paper-ez-sign` など。
  - `admins` は、このタイルで 404 だった。境界線のスタイルが描けるズームは未確認。
  - キャッシュに無いタイルは描くのに 1 枚 3〜28 秒かかった。キャッシュに当たると 0.1〜0.4 秒。同じタイルを何度も取らないよう、道具の側で手元にキャッシュする。並列で大量に取らない。
- スタイルとレベルの対応 (詳しくは [curriculum.md](curriculum.md)):
  - フルのスタイル: `osm-liberty`、`osm-bright`、`osm-carto`、`osm-fiord` (暗色)
  - 配色が違い、水も文字もほぼ無いもの: `e-paper-ez-sign` (レベル 3 で使う)
  - 文字を消したもの: `osm-liberty-no-text` と、その派生
  - 要素を絞ったもの: `railways` (と線幅違い)、`rivers` (と線幅違い)、`roads-minimal` (と `-major`、`-trunk`)、`railways_jp`

## 地名の検索: nominatim.yuiseki.net

- 所在: https://nominatim.yuiseki.net/ (作者のセルフホストの Nominatim)。
- 地名から位置のあたりを付けるのに使う。公開の nominatim.openstreetmap.org は、動作確認でもテストでも呼ばない。

## レベル 5 用の文書: 国連の PKO ミッションの地図 (PDF)

国連 Geospatial (https://www.un.org/geospatial/) が公開している、平和維持活動のミッションの地図の PDF。2026-11-04 に 5 件を取得し、`tmp/pdfs/` に置いた (`tmp/` は git に入れない)。

中身は見ていない (開かず、描かず、画像も文字も取り出していない)。確かめたのは、HTTP の応答 (200、`application/pdf`)、大きさ、SHA-256、`file` コマンドの表示 (PDF の版と、どれも 1 ページ) だけ。

| ファイル | 大きさ (バイト) | SHA-256 | 取得元 |
|---|---:|---|---|
| `unmiss_4456_r67_jan26_120.pdf` | 790,790 | `c9ca0510e6b866fb7de85aa3c857b9e4f50cb4025208aa4152ce9659060517ce` | https://www.un.org/geospatial/sites/default/files/files/documents/2026/Jan/unmiss_4456_r67_jan26_120.pdf |
| `unisfa_4467_r64_jan26_120.pdf` | 1,524,833 | `b64d46db8733c9342b834a16665e0b42bc614406a83ce8919b8aaf4c6140b587` | https://www.un.org/geospatial/sites/default/files/files/documents/2025/Nov/unisfa_4467_r64_jan26_120.pdf |
| `monusco_4412_r65_jun26_120.pdf` | 1,098,888 | `faaec7ddd1daef78bc330357cfd57eca64299aa26e7936a45cbe458af037b696` | https://www.un.org/geospatial/sites/default/files/files/documents/2026/Jan/monusco_4412_r65_jun26_120.pdf |
| `unmik_4133_r98_jan26_120.pdf` | 1,002,602 | `b2eeb28bf9be10075a096b6f6aba1625ae4f981f83a0068c0e5bc922441c1d97` | https://www.un.org/geospatial/sites/default/files/files/documents/2025/Apr/unmik_4133_r98_jan26_120.pdf |
| `minusca_4522_r31_jun24_120.pdf` | 3,384,224 | `201fa285c8a1e61ff98bd08846e3b05241883225fb2acc6c240547b14e1d5221` | https://www.un.org/geospatial/sites/default/files/files/documents/2024/Sep/minusca_4522_r31_jun24_120.pdf |

扱い:

- 2026-11-04 に、レベル 5 の道具で初めて流した (全て失敗の宣言、[記録](failures/2026-11-04-un-pko-maps.md))。その後、この 5 件を見ながら name-gcps を作ったので、これ以降は開発用の集合で、効果の評価には使えない。
- 取り直したときは、SHA-256 で同じ版かを確かめる。ファイル名の `r67` などは版、`jan26` などは時期を表すと思われる (未確認)。
- 利用条件 (https://www.un.org/geospatial/en/mandates/public): 改変した地図は派生物の土台にしてよく、そのときは国連の名称と地図の参照番号を消す。出典は "based on United Nations map" と書ける。未改変のまま載せるには許可が要る。PDF はリポジトリに入れず、再配布しない。README の図は、名称と参照番号を消してから作った (`docs/examples/mask_un_marks.py`)。

## Wikimedia Commons の地図を含む PDF 20 件 (レベル 5 の開発用)

`evals/datasets/commons-doc-maps.csv` に、20 件のファイル名、Commons のファイルページ、ライセンス (パブリックドメイン、CC BY、CC BY-SA)、作者、大きさ、SHA-256、ページ数、ページの大きさ、埋め込まれた画像の数を記録した。日本 10 件、世界 10 件で、キャンパスマップ、災害の速報図、航空の管制区域、観光の手描きの地図、政治地図、地図帳などを含む。

PDF そのものはリポジトリに入れていない。ファイルページから取得し、SHA-256 で同じ版か確かめる。開発に使う集合で、調整にも使っている。本番の評価には使わない。
