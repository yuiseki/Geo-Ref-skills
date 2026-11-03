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
  - フルのスタイル: `osm-liberty`、`osm-bright`、`osm-carto`、`osm-fiord` (暗色)、`e-paper-ez-sign`
  - 文字を消したもの: `osm-liberty-no-text` と、その派生
  - 要素を絞ったもの: `railways` (と線幅違い)、`rivers` (と線幅違い)、`roads-minimal` (と `-major`、`-trunk`)、`railways_jp`
