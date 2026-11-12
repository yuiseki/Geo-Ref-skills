# evals/agents: コーディングエージェントにスキルを渡して、ジオリファレンスできるかを測る

Codex (gpt-6-luna) と Gemini (Antigravity CLI の `gemini-3.8-flash-low`) に、このリポジトリのスキルを渡したとき、渡さないときで、地図の画像を正しく地上の座標に結べるかを比べる。仕組みは GeoAI-skills の `evals/` (Docker の上限、作業場所の作り方、実行の道具) を写したもの。

流せるエージェントは 5 つ。下の結果の表 (`results.md`) は、まだ Codex と Gemini だけ。

| `--agent` | CLI と版 | 既定のモデル | 認証 (普段の設定とは別の場所) |
|---|---|---|---|
| claude | Claude Code 2.1.321 | `claude-sonnet-5-5` | `~/.claude-evals/oauth_token` (`claude setup-token` で作る) |
| codex | Codex CLI 0.162.1 | `gpt-6-luna` | `~/.codex-evals` (`run_codex_docker.sh --login`) |
| gemini | Antigravity CLI 1.5.7 | `gemini-3.8-flash-low` | `~/.gemini-evals` (`run_gemini_docker.sh --login`、または API キー) |
| opencode | OpenCode 1.19.3 | `opencode/deepseek-v4.1-flash-free` (`EVAL_MODEL` で変える) | 要らない (無料のモデル) |
| qoder | Qoder CLI 1.1.86 | `Auto` | `~/.qoder-evals/pat` (個人のアクセストークン) |

トークンは変数の名前だけで `docker run -e` に渡し、コマンドの行にも `--dry-run` の出力にも出さない。

## 評価の場 (サンドボックス)

スキルが効くかを、エージェントの手元の環境の違いでなく、スキルのあるなしだけで比べるための場。

- イメージは `evals/Dockerfile.evals.<エージェント>` の 5 つ。違うのはエージェントの CLI とその設定だけで、OS、tesseract、ripgrep (`rg`。多くのエージェントのシステムプロンプトが検索に使えと言う)、Python のライブラリの行は同じ (`test_dockerfiles.py` が確かめる)。
- 材料はどれも固定する。元のイメージ (python と uv) はダイジェストで、CLI は版で、Python のライブラリは `requirements-evals.lock` の版で。apt の Debian のパッケージだけは、作ったときのもの。lock は、`results.md` の Codex と Gemini の実行に使ったイメージ (2026-11-09 に作った) から取った版。
- Gemini の CLI は、配布元の入れる道具が最新の版しか入れない (2026-11-12 から 13 の 1 日で 1.5.6 が 1.5.7 になった)。そこで、版の一覧 (manifest) にある本体を、版とビルドの番号で直にダウンロードし、sha512 を確かめて入れる。上げ方は Dockerfile に書いた。今は 1.5.7。`results.md` の Gemini の実行は 1.5.3 (2026-11-09 に作ったイメージ) で、この固定の前のもの。
- CLI は root の持ち物で、エージェントは自分で更新できない。自動更新も切ってある。
- 普段の `~/.claude`、`~/.codex` などの設定、フック、MCP、記憶は入らない。runner は、評価用の場所が普段の場所と同じなら止まる。

## 課題

`bench.json` の 6 つ。どれも `evals/scripts/make_task.py` で作るので、正解の変換が分かる。場所と乱数の種は `evals/matrices/` に無いもので、スキルを直すときに使っていない。

| 課題 | 何を試すか | 手がかり |
|---|---|---|
| L1-okayama | 参照と同じ配色の地図、射影の歪み | 余白付きの経緯度の枠とズーム |
| L2a-nagasaki | 灰色にした地図 | 同じ |
| L2-kumamoto | 別の配色 (osm-bright) の地図 | 同じ |
| L3-akita | 文字と記号の無い地図 | 同じ |
| L4-toyama | 場所を探す | 国 (jp) だけ |
| N-okayama-at-kochi | 陰性対照。岡山の地図に、高知を中心にした枠を渡す | 間違った枠 |

エージェントに渡す手がかりは `agent_hint` で作る。地図そのものの配色の名前は渡さず、参照に使う配色 (osm-liberty) だけを渡す。タイルの配信元は他の配色も出しているので、エージェントがそれに気づいて使うことは止めていない。

## 条件

- スキルあり: リポジトリの `git archive` (`evals/` を除く) と課題。指示文に、AGENTS.md と SKILL.md を読めという段落が入る。
- スキルなし: 課題 (画像と手がかり) だけ。指示文は、その段落が無いほかは同じ。
- どちらも、正解 (`truth.json`) と `evals/` は作業場所に入らない (`prepare_workdir` が確かめる)。
- Docker の上限は、どのエージェントと条件でも同じ。CPU 8 (`EVAL_CPUSET` で、別の 8 論理 CPU に分けて並べて流せる)、メモリ 16GB、swap 無し、プロセス 512、非 root、`--cap-drop=ALL`。作業場所だけを `/work` に載せる。
- 時間は 30 分 (`--minutes`)。コンテナの中の `timeout` で打ち切り、終了コード 124 になる。
- ネットワークは開いている (タイル、自前の Nominatim、モデルの API)。

## 採点

`score` は、各実行の `work/answer.json` を `evals/scripts/score_task.py` で正解と比べる。画像の全体に置いた 21 x 21 の格子の点で、答えの変換と正解の変換の差を測る。

| 結果 | 意味 |
|---|---|
| accurate | 誤差の最大が、画像の半径 (地上) の 1% 以下 (`--accurate-pct`。`run_matrix.py` と同じ既定) |
| inaccurate | 答えはあるが、それより大きくずれた |
| declared_failure | `status: failed` を返した |
| invalid_answer | 読めない、当てはめられない答え |
| no_answer, timeout | 答えが無い。時間切れで答えが無いときは timeout |
| correct_reject, false_accept | 陰性対照で、失敗を宣言した、答えを返した |
| provider_error | 実行の道具が 0 と 124 以外で終わり、答えが無い。エージェントの結果として数えず、流し直す |

`public_osm` の欄は、ログに公開の OSM サーバーの URL (https://.../) が出たかを示す。名前だけでは数えない。指示文 (Codex はログに写す) とスキルの文書が、呼ばないものとして名前を書いているため。出たら中身を読んで確かめる。

## 流し方

リポジトリの根から。スキルありの作業場所は、コミット済みの版 (`--rev`、既定 HEAD) から作る。

```sh
for a in claude codex gemini opencode qoder; do
  docker build -f evals/Dockerfile.evals.$a -t geo-ref-skills-evals-$a .
done
# 認証の置き場は上の表 (GeoAI-master-skills の評価と共用)

python3 evals/agents/bench.py make
EVAL_CPUSET=0-7  python3 evals/agents/bench.py run --agent codex  --cond skills   --task L1-okayama
EVAL_CPUSET=8-15 python3 evals/agents/bench.py run --agent gemini --cond baseline --task L1-okayama
uv run --with numpy --with pyproj python evals/agents/bench.py score > results.tsv
```

作業は `tmp/agent-bench/` に書く (`tasks/<課題>/{task,truth}`、`runs/<エージェント>/<条件>/<課題>-r<回>/` に作業場所、指示文、ログ、`meta.json`)。同じ回を流し直すことはできない (`--rep` を変える)。

テスト: `python3 run_tests.py evals/agents` (CI でも流す)
