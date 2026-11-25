# Gemini Web Task モード実行プロンプト：国際線15路線ディール監視

## コピー用プロンプト（Gemini Web `Task` モード用）

```text
クラウドVM（/home/spark）のシェルを使って、成田（NRT）・羽田（HND）発着の国際線15路線ディール確認スクリプトを実行し、出力されたレポート全文と圧縮バンドルを報告してください。

【絶対遵守ルール】
1. もしこの実行環境でクラウドVM（/home/spark）のシェルツールが利用できない場合は、Web検索スニペット等で代替回答を作成することは絶対に行わず、「エラー：クラウドVM（/home/spark）のシェル実行環境に接続できないため中断しました」とだけ出力して即座に終了すること。
2. 前回の実行結果やキャッシュの流用、推測による数値補完、外部サイトへのログイン・予約操作は一切行わないこと。

【実行手順（以下の1つのシェルスクリプトとしてまとめて実行すること）】
```bash
set -e
python3 ~/wb/bin/wb sync
python3 ~/wb/bin/wb status
RUN_DIR="$(python3 ~/wb/bin/wb new flight-deals)"
~/.local/share/wb-venv/bin/python ~/wb/tasks/flight_deals/run.py \
  --run-dir "$RUN_DIR" \
  --out "$RUN_DIR/out/report.md" \
  --json-out "$RUN_DIR/out/snapshot.json" \
  --bundle-b64-out "$RUN_DIR/out/bundle.b64" \
  --save-parquet
python3 ~/wb/bin/wb export "$RUN_DIR/out/report.md" --name "flight-deals-report.md"
python3 ~/wb/bin/wb export "$RUN_DIR/out/snapshot.json" --name "flight-deals-snapshot.json"
echo "===BUNDLE_B64_START==="
cat "$RUN_DIR/out/bundle.b64"
echo ""
echo "===BUNDLE_B64_END==="
```

完了後、チャット本文に以下をコードブロック（```text ... ```）で出力すること：
1. `$RUN_DIR/out/report.md` の全文（表示時のみ正規表現 `(?i)(capt[c]ha|robot|human|cloudflare|perimeterx)` に該当する英単語があれば `ボット制限` に置換）
2. `===BUNDLE_B64_START===` から `===BUNDLE_B64_END===` までの Base64 文字列全文（改変・省略厳禁）
```
