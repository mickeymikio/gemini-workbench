# Gemini Web Persistent VM — Agent Operating Manifest (`AGENTS.md`)

> **Scope Notice**:
> - **Inside Gemini Web Linux VM (`/home/spark`)**: Follow all protocols below (`python3 ~/wb/bin/wb ...`).
> - **On macOS (Antigravity local maintainer)**: This repository is the source of truth pushed to `mickeymikio/gemini-workbench`. Edit and test cleanly (using isolated `WB_HOME` temp dirs), commit, and `git push` — do **not** run `~/wb/bin/wb` against the macOS host `$HOME`.

このVM（`/home/spark`）は全タスクで共有される `$HOME` 完結・ゼロトークン型の情報収集・データ分析ワークベンチです。
環境汚染・ロック競合を防ぐため、**すべてのタスクで以下の規約を厳守してください。**

---

## 1. セッション開始時の必須プロトコル

1. **最初に `python3 ~/wb/bin/wb status` を1回実行する**
   - 空き容量の確認（全体約18GiB）、古い一時領域（`~/runs/`）の自動GC、Chromium準備状態の確認、および蓄積済みデータセット（`~/data/datasets/`）の一覧取得が自動で行われます。
   - ユーザーから「ツールを更新して」「`wb sync` して」と指示された場合は `python3 ~/wb/bin/wb sync` を実行してください（認証不要の Public HTTPS で最新化されます）。
2. **タスク専用の隔離ディレクトリを作成する**
   - `RUN_DIR="$(python3 ~/wb/bin/wb new <short-topic-slug>)"` を実行し、ダウンロード・一時スクリプト・中間生成物はすべて `"$RUN_DIR"` 配下にのみ作成してください。
   - `$HOME` 直下や `~/wb/` 内での作業・一時ファイル作成は禁止です。

---

## 2. Python・パッケージ実行ルール（2層分離）

### 第一層：定番ベース環境（0秒起動・書き換え禁止）
- パス：`~/.local/share/wb-venv/bin/python`
- 導入済み：`uv`, `duckdb`, `polars`, `pyarrow`, `pydantic`, `httpx`, `curl_cffi`, `trafilatura`, `selectolax`, `beautifulsoup4`, `lxml`, `yt-dlp`, `playwright`, `matplotlib`, `seaborn`, `jinja2`, `tenacity`, `zstandard`
- **禁止**：`wb-venv` に対して `pip install` でパッケージを追加・変更しないでください。

### 第二層：特殊パッケージが必要な場合（PEP 723 単一ファイル分離）
- ベース環境にないライブラリが必要な場合は、`$RUN_DIR/scripts/` 内のスクリプト冒頭に PEP 723 メタデータを記述し、`SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt ~/.local/share/wb-venv/bin/uv run script.py` で実行してください。

---

## 3. Web情報収集・TLSプロキシ・フルブラウザ描画ルール

1. **外向きTLSプロキシ証明書の扱い**
   - このVMのHTTPS通信はプロキシ経由のため、Python HTTPクライアントや `git` を使う際は `/etc/ssl/certs/ca-certificates.crt`（`SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `GIT_SSL_CAINFO`）を参照してください。
2. **SPA・動的描画サイトは必ず `browser_helper.py` 経由で Playwright を使う**
   - `browser_helper.py` は `/dev/shm` 対策（`--disable-dev-shm-usage`）およびプロキシTLS対応（`ignore_https_errors=True`）を自動適用します。
   - **CLIワンライナー抽出**：
     ```bash
     ~/.local/share/wb-venv/bin/python ~/wb/lib/browser_helper.py "https://example.com" --markdown > "$RUN_DIR/page.md"
     ```
   - **Pythonからの利用**：
     ```python
     import os, sys
     sys.path.insert(0, os.path.expanduser("~/wb/lib"))
     from browser_helper import sync_open_page

     with sync_open_page(download_dir=f"{run_dir}/downloads") as page:
         page.goto("https://example.com", wait_until="domcontentloaded")
         html = page.content()
     ```

---

## 4. データ蓄積（Parquet + DuckDB）と成果物エクスポート（`wb export`）

- **単一の `.duckdb` / `.sqlite` ファイルを `~/data/` に永続保存しないこと**（同時実行時のロック競合を防ぐため）。
- 再利用価値のある構造化データは `~/data/datasets/<topic>/YYYY-MM-DD.parquet` として保存し、`~/wb/lib/duckdb_helper.py` の `append_parquet` / `query_parquet` で操作してください。
- 最終レポート・CSV・グラフ画像・データ一式をユーザーに渡す際は、以下で現在のチャット作業ディレクトリ（`/working_dir/...`）へ書き出してダウンロード可能にするか、指示に応じて `@Google ドライブ` / `@Google ドキュメント` 連携で保存してください：
  ```bash
  python3 ~/wb/bin/wb export "$RUN_DIR/out" --name "report-bundle"
  ```

---

## 5. 定型タスクスイート（`tasks/`）

- **国際線15路線ディール実画面確認タスク（`tasks/flight_deals/run.py`）**：
  ```bash
  RUN_DIR="$(python3 ~/wb/bin/wb new flight-deals)"
  ~/.local/share/wb-venv/bin/python ~/wb/tasks/flight_deals/run.py --run-dir "$RUN_DIR" --out "$RUN_DIR/out/report.md" --save-parquet
  python3 ~/wb/bin/wb export "$RUN_DIR/out/report.md" --name "flight-deals-report.md"
  ```

---

## 6. サンドボックス安全規約

- `~/.bashrc` や `~/.profile` の書き換え、`sudo` / `uname` / `df` 等のシステム偵察コマンドの実行、およびVM内ファイルへの認証トークン保存は行わないでください。
