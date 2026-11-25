# Gemini Web Task モード実行プロンプト：国際線15路線ディール監視

> **注意（実機検証結果に基づく運用ガイド）**：
> - Gemini Web の「スケジュール設定済み（`gemini.google.com/scheduled`）」は通常チャット専用であり、`/home/spark` クラウドVMへの接続およびシェル実行の無人承認には対応していません。
> - **完全無人の毎日定期実行**には、同梱の macOS 自動実行構成（`launchd` または Antigravity `/schedule`）を使用してください。
> - **Gemini Web の `Task` モード（クラウドVM `/home/spark`）でオンデマンド実行する場合**は、入力欄に `Mac mini ×` チップが付いていないことを確認のうえ、以下のプロンプトを貼り付けて送信し、`許可する` をクリックしてください。

---

## コピー用プロンプト（Gemini Web `Task` モード用）

```text
クラウドVM（/home/spark）のシェルを使って、成田（NRT）・羽田（HND）発着の国際線15路線ディール確認スクリプトを実行し、出力されたレポート全文を一字一句改変・省略せずに報告してください。

【絶対遵守ルール】
1. もしこの実行環境でクラウドVM（/home/spark）のシェルツールが利用できない場合は、Web検索スニペット等で代替回答を作成することは絶対に行わず、「エラー：クラウドVM（/home/spark）のシェル実行環境に接続できないため中断しました」とだけ出力して即座に終了すること。
2. 前回の実行結果やキャッシュの流用、推測による数値補完、外部サイトへのログイン・予約操作は一切行わないこと。

【実行手順】
1. `python3 ~/wb/bin/wb sync && python3 ~/wb/bin/wb status` を実行してワークベンチを最新化する。
2. `RUN_DIR="$(python3 ~/wb/bin/wb new flight-deals)"` で今回の隔離ディレクトリを作成する。
3. 以下の単一コマンドを実行する：
   `~/.local/share/wb-venv/bin/python ~/wb/tasks/flight_deals/run.py --run-dir "$RUN_DIR" --out "$RUN_DIR/out/report.md" --save-parquet`
4. `python3 ~/wb/bin/wb export "$RUN_DIR/out/report.md" --name "flight-deals-report.md"` を実行し、さらに `$RUN_DIR/out/report.md` の中身全文をそのままチャット本文に出力する。
```
