# evals/agents: コーディングエージェントにスキルを渡して、ジオリファレンスできるかを測る

Codex (gpt-6-luna) と Gemini (Antigravity CLI の `gemini-3.8-flash-low`) に、このリポジトリのスキルを渡したとき、渡さないときで、地図の画像を正しく地上の座標に結べるかを比べる。仕組みは GeoAI-skills の `evals/` (Docker の上限、作業場所の作り方、実行の道具) を写したもの。

流せるエージェントは 5 つ。結果の表 (`results.md`) は、Codex、Gemini、Qoder、OpenCode (Hy4 Flash) の 4 つ。

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
- ネットワークは開いている (タイル、自前の Nominatim、モデルの API)。ただし、指示文が禁じる公開の OSM サーバーは、`blocked-hosts.txt` の名前を `--add-host=...:0.0.0.0` で塞いで、コンテナから届かない (Qoder のスキルなしの 1 回が公開の Overpass を呼んだため、2026-11-17 から)。

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

トークンの欄は、各 CLI が残した記録から数える。`tok_in` はキャッシュの読み出しも含めた入力の全部 (`tok_cached` はそのうちのキャッシュの読み出し)、`tok_out` は推論も含めた出力、`calls` はモデルの呼び出しの回数。OpenCode はログの `step_finish`、Gemini は `step_update` の終わったもの、Claude Code は `result` から。Qoder はトークンを 0 と記録するので、使ったクレジット (`credits`) だけ。Codex は、ログには合計だけを出し、内訳を評価用の場所 (`$EVAL_CODEX_HOME/sessions`) の会話の記録に書く。`run` は終わったあとに、その記録を実行の場所へ `codex-session.jsonl` として写す。どの記録かは、Codex が出す合計 (入力 − キャッシュ + 出力) で決まる。それより前の実行には `bench.py codex-sessions` で写す。

`public_osm` の欄は、ログに公開の OSM サーバーの URL (https://.../) が出たかを示す。名前だけでは数えない。指示文 (Codex はログに写す) とスキルの文書が、呼ばないものとして名前を書いているため。出たら中身を読んで確かめる。

## 結果を読むときの決まり

ISUCON の本番 8 時間を Claude Code に無人で解かせた記録 ([準備編](https://zenn.dev/luvtechno/articles/isucon2026-preparation)、[当日編](https://zenn.dev/luvtechno/articles/isucon2026-competition-day)) から、この評価に当てはまるものを取り入れた。

- 1 回の実行では、条件の差を言わない。その記録では、同じコミットでもスコアが最大で約 21% ばらつき、12 回の走行の幅が終盤の施策の差より大きかった。`summary` は、エージェント、条件、課題ごとに回数 (`n`) と良い結果 (accurate、correct_reject) の数を数え、1 回だけのものに `single` を付ける。`results.md` の表は、ことわりの無いかぎり 1 回ずつ。
- 評価の場の不具合を、エージェントの失敗として数えない。その記録では、評価の環境の誤りがエージェントの判断を誤らせた。`run` は、指示文が名指すタイルと Nominatim が 200 を返すかを先に確かめ、返さなければ何も書かずに止まる。
- 何で流したかを、名前でなく実体で残す。イメージは同じ名前で作り直される (CLI の版が動く) ので、`meta.json` に `image` と `image_id` を書く。
- 個人の設定を混ぜない。混ぜると条件の比較にならない。ここではコンテナがそれを受け持つ (上の「評価の場」)。

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
python3 evals/agents/bench.py summary results.tsv   # 回数と良い結果の数。single は 1 回だけ
python3 evals/agents/bench.py codex-sessions        # Codex の実行に、トークンの内訳の記録を写す
```

スキルの版などを変えて比べるときは、`run` に `--variant <名前>` を付ける。実行は `<エージェント>+<名前>` として、普段のものと分けて置かれ、数えられる。

作業は `tmp/agent-bench/` に書く (`tasks/<課題>/{task,truth}`、`runs/<エージェント>/<条件>/<課題>-r<回>/` に作業場所、指示文、ログ、`meta.json`、Codex は `codex-session.jsonl`)。同じ回を流し直すことはできない (`--rep` を変える)。

テスト: `python3 run_tests.py evals/agents` (CI でも流す)
