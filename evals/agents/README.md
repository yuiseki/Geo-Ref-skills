# evals/agents: コーディングエージェントにスキルを渡して、ジオリファレンスできるかを測る

Codex (gpt-6-luna) と Gemini (Antigravity CLI の `gemini-3.8-flash-low`) に、このリポジトリのスキルを渡したとき、渡さないときで、地図の画像を正しく地上の座標に結べるかを比べる。仕組みは GeoAI-skills の `evals/` (Docker の上限、作業場所の作り方、実行の道具) を写したもの。

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
- Docker の上限は両方で同じ。CPU 8 (`EVAL_CPUSET` で、別の 8 論理 CPU に分けて並べて流せる)、メモリ 16GB、swap 無し、プロセス 512、非 root、`--cap-drop=ALL`。作業場所だけを `/work` に載せる。
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
docker build -f Dockerfile.evals.codex -t geo-ref-skills-evals-codex .
docker build -f Dockerfile.evals.gemini -t geo-ref-skills-evals-gemini .   # agy の版は AGY_VERSION (1.5.3) に固定
# 認証は ~/.codex-evals と ~/.gemini-evals (GeoAI-skills の評価と共用、普段の ~/.codex、~/.gemini とは別)

python3 evals/agents/bench.py make
EVAL_CPUSET=0-7  python3 evals/agents/bench.py run --agent codex  --cond skills   --task L1-okayama
EVAL_CPUSET=8-15 python3 evals/agents/bench.py run --agent gemini --cond baseline --task L1-okayama
uv run --with numpy --with pyproj python evals/agents/bench.py score > results.tsv
```

作業は `tmp/agent-bench/` に書く (`tasks/<課題>/{task,truth}`、`runs/<エージェント>/<条件>/<課題>-r<回>/` に作業場所、指示文、ログ、`meta.json`)。同じ回を流し直すことはできない (`--rep` を変える)。

テスト: `cd evals/agents && uvx --with pytest --with numpy --with pyproj python -m pytest -q test_bench.py`
