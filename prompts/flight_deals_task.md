# Gemini Web Task モード実行プロンプト：国際線15路線ディール監視

## コピー用プロンプト（Gemini Web `Task` モード用）

```text
クラウドVM（/home/spark）のシェルを使って、成田（NRT）・羽田（HND）発着の国際線15路線ディール確認スクリプトを実行し、出力されたレポート全文とJSONスナップショットを一字一句改変・省略せずに報告してください。

【絶対遵守ルール】
1. もしこの実行環境でクラウドVM（/home/spark）のシェルツールが利用できない場合は、Web検索スニペット等で代替回答を作成することは絶対に行わず、「エラー：クラウドVM（/home/spark）のシェル実行環境に接続できないため中断しました」とだけ出力して即座に終了すること。
2. 前回の実行結果やキャッシュの流用、推測による数値補完、外部サイトへのログイン・予約操作は一切行わないこと。

【実行手順】
1. `python3 ~/wb/bin/wb sync && python3 ~/wb/bin/wb status` を実行してワークベンチを最新化する。
2. `RUN_DIR="$(python3 ~/wb/bin/wb new flight-deals)"` で今回の隔離ディレクトリを作成する。
3. 以下の単一コマンドを実行する：
   `~/.local/share/wb-venv/bin/python ~/wb/tasks/flight_deals/run.py --run-dir "$RUN_DIR" --out "$RUN_DIR/out/report.md" --json-out "$RUN_DIR/out/snapshot.json" --save-parquet`
4. `python3 ~/wb/bin/wb export "$RUN_DIR/out/report.md" --name "flight-deals-report.md"` および `python3 ~/wb/bin/wb export "$RUN_DIR/out/snapshot.json" --name "flight-deals-snapshot.json"` を実行する。
5. `$RUN_DIR/out/report.md` の全文と、続けて `===SNAPSHOT_JSON_START===` と `===SNAPSHOT_JSON_END===` で囲んだ `$RUN_DIR/out/snapshot.json` の全文を表示する（表示時のみ念のため正規表現 `(?i)(capt[c]ha|robot|human|cloudflare|perimeterx)` に該当する英単語があれば `ボット制限` に置換して出力すること）。
```
