# gemini-workbench

Gemini Web の専用永続VM（`/home/spark`）を、**認証トークンを一切VM内に置かないゼロ・トークン構成**で安全に運用するためのワークベンチリポジトリです。

## 特徴

- **ゼロ・トークン＆単方向同期（`wb sync`）**：Public HTTPS 経由で `~/wb` を1コマンド最新化（VM側に秘密鍵・PATを一切保持しないため漏洩リスクゼロ、かつ物理的に Read-Only）。
- **環境腐敗・競合の防止（`wb new` / `wb status`）**：タスクごとに `~/runs/<日時-slug>/` を自動分離し、7日経過した一時ファイルを自動GC。
- **Playwright Chromium フルレンダリング対応（`lib/browser_helper.py`）**：コンテナの `/dev/shm` 制限対策および外向きTLSプロキシ環境（`ignore_https_errors=True`・システムCA設定）を自動適用。
- **ロックフリーなデータ蓄積（`lib/duckdb_helper.py`）**：日付パーティション分割 Parquet（`~/data/datasets/<topic>/*.parquet`）＋ インメモリ DuckDB クエリにより、複数チャットの同時実行でもロック競合ゼロ。
- **1コマンド成果物パッケージ化（`wb export`）**：レポートやCSV一式を現在のチャット作業領域へ即座にファイル／ZIP書き出し。

---

## 専用VMでの初回セットアップ／復元ワンライナー

Gemini Web の **`Task` モード**（入力欄に `Mac mini` チップが付いていないクラウドVM状態）で以下を実行します：

```bash
GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt git clone https://github.com/mickeymikio/gemini-workbench.git ~/wb
bash ~/wb/bootstrap.sh
```

以降のツール更新はいつでも1コマンドで完了します：

```bash
python3 ~/wb/bin/wb sync
```
