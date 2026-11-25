#!/usr/bin/env python3
"""Zero-dependency HTML dashboard generator for 15-route international flight deals.

Supports two output modes from the same daily JSON snapshots (`snapshots/*.json`):
1. `--mode standalone` (default): Full standalone HTML dashboard (`index.html`) viewable in any browser.
2. `--mode artifact`: Antigravity Generative UI HTML artifact strictly using allowlisted gstatic
   Tailwind + Antigravity semantic CSS theme variables (`--background`, `--card`, `--foreground`, etc.).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

ALL_15_META: list[dict[str, Any]] = [
    {"code": "NRT-ICN", "origin": "NRT", "dest": "ICN", "city_ja": "ソウル仁川", "region": "asia"},
    {"code": "HND-GMP", "origin": "HND", "dest": "GMP", "city_ja": "ソウル金浦", "region": "asia"},
    {"code": "NRT-TPE", "origin": "NRT", "dest": "TPE", "city_ja": "台北桃園", "region": "asia"},
    {"code": "HND-TSA", "origin": "HND", "dest": "TSA", "city_ja": "台北松山", "region": "asia"},
    {"code": "NRT-HKG", "origin": "NRT", "dest": "HKG", "city_ja": "香港", "region": "asia"},
    {"code": "NRT-BKK", "origin": "NRT", "dest": "BKK", "city_ja": "バンコク", "region": "asia"},
    {"code": "HND-SIN", "origin": "HND", "dest": "SIN", "city_ja": "シンガポール", "region": "asia"},
    {"code": "NRT-HNL", "origin": "NRT", "dest": "HNL", "city_ja": "ホノルル", "region": "long"},
    {"code": "HND-LAX", "origin": "HND", "dest": "LAX", "city_ja": "ロサンゼルス", "region": "long"},
    {"code": "NRT-SGN", "origin": "NRT", "dest": "SGN", "city_ja": "ホーチミン", "region": "asia"},
    {"code": "NRT-SYD", "origin": "NRT", "dest": "SYD", "city_ja": "シドニー", "region": "long"},
    {"code": "NRT-HAN", "origin": "NRT", "dest": "HAN", "city_ja": "ハノイ", "region": "asia"},
    {"code": "NRT-MNL", "origin": "NRT", "dest": "MNL", "city_ja": "マニラ", "region": "asia"},
    {"code": "NRT-SAI", "origin": "NRT", "dest": "SAI", "city_ja": "シェムリアップ", "region": "asia"},
    {"code": "NRT-DAD", "origin": "NRT", "dest": "DAD", "city_ja": "ダナン", "region": "asia"},
]


def load_snapshots(snapshots_dir: Path) -> list[dict[str, Any]]:
    if not snapshots_dir.is_dir():
        return []
    by_date: dict[str, dict[str, Any]] = {}
    for fp in sorted(snapshots_dir.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and "run_date_jst" in data and "observations" in data:
            by_date[str(data["run_date_jst"])] = data
    return [by_date[k] for k in sorted(by_date.keys(), reverse=True)]


def build_dashboard_html(snapshots: Sequence[dict[str, Any]], mode: str = "artifact") -> str:
    payload_json = json.dumps(
        {"routes": ALL_15_META, "snapshots": list(snapshots)},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    standalone_fallback_style = ""
    if mode == "standalone":
        standalone_fallback_style = """
  <style>
    :root {
      --background: #0b1020;
      --card: #131b31;
      --card-border: #243154;
      --border: #243154;
      --foreground: #f1f5f9;
      --muted-foreground: #94a3b8;
      --primary: #38bdf8;
      --primary-foreground: #082f49;
      --secondary: #1e293b;
      --secondary-foreground: #e2e8f0;
      --accent: #1e293b;
      --link: #38bdf8;
      --success: #22c55e;
      --warning: #f59e0b;
      --error: #ef4444;
      --chart-1: #38bdf8;
      --chart-2: #22c55e;
      --chart-3: #f59e0b;
      --chart-4: #a78bfa;
    }
    @media (prefers-color-scheme: light) {
      :root {
        --background: #f8fafc;
        --card: #ffffff;
        --card-border: #e2e8f0;
        --border: #e2e8f0;
        --foreground: #0f172a;
        --muted-foreground: #64748b;
        --primary: #0284c7;
        --primary-foreground: #ffffff;
        --secondary: #f1f5f9;
        --secondary-foreground: #0f172a;
        --accent: #f1f5f9;
        --link: #0284c7;
        --success: #16a34a;
        --warning: #d97706;
        --error: #dc2626;
      }
    }
  </style>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>NRT・HND 国際線15路線ディール監視ダッシュボード</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>{standalone_fallback_style}
</head>
<body class="bg-[var(--background)] text-[var(--foreground)] antialiased p-4 md:p-6">
  <div class="max-w-7xl mx-auto space-y-6">
    <!-- Header -->
    <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pb-4 border-b border-[var(--border)]">
      <div>
        <div class="flex items-center gap-2">
          <span class="px-2 py-0.5 text-xs font-semibold rounded bg-[var(--secondary)] text-[var(--primary)] border border-[var(--border)]">Gemini Cloud VM (/home/spark) 実画面検証</span>
          <span class="text-xs text-[var(--muted-foreground)]">毎日 13:00 JST 自動更新</span>
        </div>
        <h1 class="text-xl md:text-2xl font-bold mt-1">成田（NRT）・羽田（HND）国際線15路線 往復最安値＆ディール監視</h1>
      </div>
      <div class="flex items-center gap-3">
        <label class="text-xs text-[var(--muted-foreground)]" for="snapSelect">観測日：</label>
        <select id="snapSelect" class="text-xs rounded px-3 py-1.5 bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)] focus:outline-none"></select>
      </div>
    </div>

    <!-- KPI Row -->
    <div id="kpiGrid" class="grid grid-cols-2 lg:grid-cols-4 gap-3"></div>

    <!-- >=40% Deals Spotlight -->
    <section class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 md:p-5 space-y-3">
      <div class="flex items-center justify-between gap-2">
        <div>
          <h2 class="text-base font-bold flex items-center gap-2">
            <span>40%以上オフ ディール（同一サイト通常価格比・割引率順）</span>
            <span id="dealBadge" class="px-2 py-0.5 text-xs rounded-full font-mono tabular-nums bg-[var(--secondary)] text-[var(--success)]"></span>
          </h2>
          <p class="text-xs text-[var(--muted-foreground)] mt-0.5">出発日・帰国日指定の実検索結果画面で確認された税込総額と、同サイト表示の通常価格（中央値）のペア比較</p>
        </div>
      </div>
      <div id="dealsContainer" class="grid grid-cols-1 lg:grid-cols-2 gap-3"></div>
    </section>

    <!-- Discount Bar Chart + Site Health -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <section class="lg:col-span-2 bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 md:p-5 space-y-3">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-bold">路線別 割引率ランキング（通常価格取得済み路線）</h2>
          <span class="text-xs text-[var(--muted-foreground)]">赤破線 = 40%オフ基準</span>
        </div>
        <div id="discountBars" class="space-y-2"></div>
      </section>

      <section class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 md:p-5 space-y-3">
        <h2 class="text-sm font-bold">対象7サイト 実画面到達ステータス</h2>
        <p class="text-xs text-[var(--muted-foreground)]">ボット検知・チャレンジ画面は突破せず規約どおり記録</p>
        <div id="siteStatusList" class="space-y-2"></div>
      </section>
    </div>

    <!-- Full 15-Route Interactive Table -->
    <section class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 md:p-5 space-y-4">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-bold">全15路線 最安値マトリクス（参考観測・サイト横断一覧）</h2>
          <p class="text-xs text-[var(--muted-foreground)]">※異サイト間の価格・通常価格の混ぜ合わせ計算は一切行っていません</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <input id="searchInput" type="search" placeholder="空港・都市・航空会社で検索..." class="text-xs rounded px-3 py-1.5 bg-[var(--background)] text-[var(--foreground)] border border-[var(--border)] focus:outline-none" />
          <select id="regionFilter" class="text-xs rounded px-2.5 py-1.5 bg-[var(--background)] text-[var(--foreground)] border border-[var(--border)]">
            <option value="all">全エリア（15路線）</option>
            <option value="deals">40%以上オフのみ</option>
            <option value="asia">アジア短・中距離（12路線）</option>
            <option value="long">中・長距離 HNL/LAX/SYD（3路線）</option>
            <option value="lcc">LCC便のみ</option>
          </select>
          <select id="sortSelect" class="text-xs rounded px-2.5 py-1.5 bg-[var(--background)] text-[var(--foreground)] border border-[var(--border)]">
            <option value="default">標準路線順</option>
            <option value="discount">割引率が大きい順</option>
            <option value="price">最安値が安い順（円換算目安）</option>
            <option value="dep">出発日が近い順</option>
          </select>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-xs text-left border-collapse">
          <thead>
            <tr class="border-b border-[var(--border)] text-[var(--muted-foreground)]">
              <th class="py-2.5 px-2 font-semibold">路線</th>
              <th class="py-2.5 px-2 font-semibold">最安日程（往復）</th>
              <th class="py-2.5 px-2 font-semibold">確認最安値</th>
              <th class="py-2.5 px-2 font-semibold">同サイト通常価格</th>
              <th class="py-2.5 px-2 font-semibold">割引率</th>
              <th class="py-2.5 px-2 font-semibold">航空会社・手荷物・経由</th>
              <th class="py-2.5 px-2 font-semibold">出典・他サイト観測</th>
              <th class="py-2.5 px-2 font-semibold text-right">実画面URL</th>
            </tr>
          </thead>
          <tbody id="routeTableBody" class="divide-y divide-[var(--border)]"></tbody>
        </table>
      </div>
    </section>
  </div>

  <script>
    const DATA = {payload_json};
    const FX_JPY = {{ JPY: 1, USD: 155, KRW: 0.11, EUR: 163 }};
    const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];
    const ALL_SITES = ['Google Flights', 'KAYAK', 'Cheapflights', 'momondo', 'Priceline', 'catchfrog.ai', 'Skyscanner'];

    function esc(s) {{
      return String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    }}

    function fmtMoney(val, cur) {{
      if (val == null) return '—';
      const c = (cur || 'JPY').toUpperCase();
      if (c === 'JPY') return '¥' + Math.round(val).toLocaleString('ja-JP');
      if (c === 'USD') return '$' + Math.round(val).toLocaleString('en-US') + ' (USD)';
      return val.toLocaleString() + ' ' + c;
    }}

    function fmtDateJa(iso) {{
      if (!iso) return '—';
      const [y, m, d] = iso.split('-').map(Number);
      const dt = new Date(Date.UTC(y, m - 1, d));
      const w = WEEKDAYS[dt.getUTCDay()];
      return `${{y}}/${{String(m).padStart(2,'0')}}/${{String(d).padStart(2,'0')}} (${{w}})`;
    }}

    function approxJpy(obs) {{
      if (!obs) return Infinity;
      return obs.lowest_price * (FX_JPY[(obs.currency || 'JPY').toUpperCase()] || 1);
    }}

    const snapSelect = document.getElementById('snapSelect');
    const searchInput = document.getElementById('searchInput');
    const regionFilter = document.getElementById('regionFilter');
    const sortSelect = document.getElementById('sortSelect');

    function init() {{
      if (!DATA.snapshots || DATA.snapshots.length === 0) {{
        document.getElementById('kpiGrid').innerHTML = '<div class="col-span-4 text-xs text-[var(--muted-foreground)]">スナップショットがまだありません。</div>';
        return;
      }}
      DATA.snapshots.forEach((s, i) => {{
        const opt = document.createElement('option');
        opt.value = String(i);
        opt.textContent = `${{s.run_date_jst}}（${{s.executed_at_jst}}）`;
        snapSelect.appendChild(opt);
      }});
      snapSelect.addEventListener('change', render);
      searchInput.addEventListener('input', render);
      regionFilter.addEventListener('change', render);
      sortSelect.addEventListener('change', render);
      render();
    }}

    function render() {{
      const idx = Number(snapSelect.value || 0);
      const snap = DATA.snapshots[idx];
      const prevSnap = DATA.snapshots[idx + 1] || null;
      if (!snap) return;

      const obsByRoute = {{}};
      (snap.observations || []).forEach(o => {{
        (obsByRoute[o.route_code] = obsByRoute[o.route_code] || []).push(o);
      }});

      const prevBestJpy = {{}};
      if (prevSnap) {{
        (prevSnap.observations || []).forEach(o => {{
          const v = approxJpy(o);
          if (!(o.route_code in prevBestJpy) || v < prevBestJpy[o.route_code]) prevBestJpy[o.route_code] = v;
        }});
      }}

      const deals = (snap.observations || [])
        .filter(o => o.is_deal_40_off)
        .sort((a, b) => (b.discount_pct || 0) - (a.discount_pct || 0));

      const maxDisc = deals.length > 0
        ? Math.max(...deals.map(d => d.discount_pct || 0))
        : Math.max(0, ...(snap.observations || []).map(o => o.discount_pct || 0));

      // 1. KPI Cards
      document.getElementById('kpiGrid').innerHTML = `
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-3.5">
          <div class="text-xs text-[var(--muted-foreground)]">最終確認日時（JST）</div>
          <div class="text-sm font-bold font-mono tabular-nums mt-1">${{esc(snap.executed_at_jst)}}</div>
          <div class="text-xs text-[var(--muted-foreground)] mt-1">前回流用なし・毎回実画面確認</div>
        </div>
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-3.5">
          <div class="text-xs text-[var(--muted-foreground)]">確認できた路線数</div>
          <div class="text-xl font-bold font-mono tabular-nums mt-1 text-[var(--primary)]">${{snap.confirmed_route_count}} <span class="text-sm text-[var(--muted-foreground)]">/ ${{snap.total_routes}}</span></div>
          <div class="text-xs text-[var(--muted-foreground)] mt-1">成田（NRT）・羽田（HND）国際線</div>
        </div>
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-3.5">
          <div class="text-xs text-[var(--muted-foreground)]">40%以上オフ ディール数</div>
          <div class="text-xl font-bold font-mono tabular-nums mt-1 ${{deals.length > 0 ? 'text-[var(--success)]' : ''}}">${{deals.length}} 件</div>
          <div class="text-xs text-[var(--muted-foreground)] mt-1">同一サイト通常価格（中央値）比</div>
        </div>
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-3.5">
          <div class="text-xs text-[var(--muted-foreground)]">最大割引率</div>
          <div class="text-xl font-bold font-mono tabular-nums mt-1 text-[var(--warning)]">${{maxDisc.toFixed(1)}}% OFF</div>
          <div class="text-xs text-[var(--muted-foreground)] mt-1">今後約6か月（+7〜180日）最安日程</div>
        </div>
      `;

      // 2. Deals Spotlight
      document.getElementById('dealBadge').textContent = `${{deals.length}}件検出`;
      const dealsEl = document.getElementById('dealsContainer');
      if (deals.length === 0) {{
        dealsEl.innerHTML = `<div class="col-span-2 text-xs text-[var(--muted-foreground)] py-3">今回の実画面確認では、同一サイトの通常価格比40%以上オフとなる運賃はありませんでした。</div>`;
      }} else {{
        dealsEl.innerHTML = deals.map((d, i) => {{
          const rangeNote = (d.typical_low && d.typical_high)
            ? `（表示レンジ ${{fmtMoney(d.typical_low, d.typical_currency)}}〜${{fmtMoney(d.typical_high, d.typical_currency)}} 中央値）`
            : '';
          const bagText = d.is_lcc
            ? (d.checked_baggage || '受託手荷物：要確認')
            : (d.checked_baggage || 'フルサービスキャリア');
          return `
            <div class="rounded-lg border border-[var(--border)] bg-[var(--background)] p-4 flex flex-col justify-between gap-3">
              <div class="space-y-2">
                <div class="flex items-start justify-between gap-2">
                  <div>
                    <span class="text-xs font-mono text-[var(--muted-foreground)]">#${{i + 1}} ${{esc(d.source_site)}}</span>
                    <h3 class="text-base font-bold">${{esc(d.origin)}} → ${{esc(d.dest)}}（${{esc(d.city_ja)}}）</h3>
                  </div>
                  <span class="px-2.5 py-1 rounded-md text-xs font-bold font-mono tabular-nums bg-[var(--secondary)] text-[var(--success)] border border-[var(--border)]">
                    -${{d.discount_pct.toFixed(1)}}% OFF
                  </span>
                </div>
                <div class="flex items-baseline gap-3">
                  <span class="text-xl font-bold font-mono tabular-nums text-[var(--primary)]">${{fmtMoney(d.lowest_price, d.currency)}}</span>
                  <span class="text-xs text-[var(--muted-foreground)]">（${{esc(d.tax_status)}}）</span>
                  <span class="text-xs text-[var(--muted-foreground)] line-through font-mono">${{fmtMoney(d.typical_price, d.typical_currency)}}</span>
                </div>
                <div class="text-xs text-[var(--muted-foreground)]">通常価格：${{fmtMoney(d.typical_price, d.typical_currency)}} ${{esc(rangeNote)}}</div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-xs pt-1">
                  <div><span class="text-[var(--muted-foreground)]">日程：</span><span class="font-mono">${{fmtDateJa(d.dep_date)}} 〜 ${{fmtDateJa(d.ret_date)}}</span></div>
                  <div><span class="text-[var(--muted-foreground)]">航空会社：</span><span class="font-semibold">${{esc(d.airline)}}</span></div>
                  <div><span class="text-[var(--muted-foreground)]">経路：</span>${{esc(d.stops_text)}}</div>
                  <div><span class="text-[var(--muted-foreground)]">手荷物：</span>${{esc(bagText)}}</div>
                </div>
              </div>
              <div class="pt-2 border-t border-[var(--border)] flex items-center justify-between">
                <span class="text-xs text-[var(--muted-foreground)]">${{d.is_lcc ? 'LCC運賃' : '通常キャリア'}}</span>
                <a href="${{esc(d.search_url)}}" target="_blank" rel="noopener noreferrer" class="text-xs font-semibold text-[var(--link)] hover:underline">
                  日付入り実検索結果画面を開く ↗
                </a>
              </div>
            </div>
          `;
        }}).join('');
      }}

      // 3. Discount Bar Chart (Google Flights / same-site typical_price available)
      const withDisc = [];
      DATA.routes.forEach(r => {{
        const list = (obsByRoute[r.code] || []).filter(o => o.discount_pct != null);
        if (list.length > 0) {{
          list.sort((a, b) => (b.discount_pct || 0) - (a.discount_pct || 0));
          withDisc.push({{ meta: r, obs: list[0] }});
        }}
      }});
      withDisc.sort((a, b) => (b.obs.discount_pct || 0) - (a.obs.discount_pct || 0));

      document.getElementById('discountBars').innerHTML = withDisc.map(({{ meta, obs }}) => {{
        const pct = Math.max(0, Math.min(80, obs.discount_pct || 0));
        const widthPct = (pct / 80) * 100;
        const isDeal = obs.is_deal_40_off;
        const barColor = isDeal ? 'var(--success)' : 'var(--chart-1)';
        return `
          <div class="grid grid-cols-12 items-center gap-2 text-xs">
            <div class="col-span-4 sm:col-span-3 truncate font-medium" title="${{esc(meta.code)}} ${{esc(meta.city_ja)}}">
              <span class="font-mono">${{esc(meta.code)}}</span> <span class="text-[var(--muted-foreground)]">${{esc(meta.city_ja)}}</span>
            </div>
            <div class="col-span-5 sm:col-span-6 relative h-4 rounded bg-[var(--secondary)] overflow-hidden">
              <div class="absolute top-0 bottom-0 border-l border-dashed border-[var(--error)] z-10" style="left: 50%;" title="40%オフ基準"></div>
              <div class="h-full rounded transition-all" style="width: ${{widthPct.toFixed(1)}}%; background: ${{barColor}};"></div>
            </div>
            <div class="col-span-3 text-right font-mono tabular-nums">
              <span class="${{isDeal ? 'font-bold text-[var(--success)]' : ''}}">${{(obs.discount_pct || 0).toFixed(1)}}%</span>
              <span class="text-[var(--muted-foreground)] hidden sm:inline"> (${{fmtMoney(obs.lowest_price, obs.currency)}})</span>
            </div>
          </div>
        `;
      }}).join('');

      // 4. Site Reachability Status
      const siteOkCount = {{}};
      const siteFailReason = {{}};
      ALL_SITES.forEach(s => {{ siteOkCount[s] = 0; }});
      (snap.observations || []).forEach(o => {{
        siteOkCount[o.source_site] = (siteOkCount[o.source_site] || 0) + 1;
      }});
      (snap.failures || []).forEach(f => {{
        if (!siteFailReason[f.source_site]) siteFailReason[f.source_site] = f.reason_ja;
      }});

      document.getElementById('siteStatusList').innerHTML = ALL_SITES.map(site => {{
        const ok = siteOkCount[site] || 0;
        const badge = ok > 0
          ? `<span class="px-2 py-0.5 rounded text-xs font-mono bg-[var(--secondary)] text-[var(--success)]">${{ok}}/${{snap.total_routes}} 取得</span>`
          : `<span class="px-2 py-0.5 rounded text-xs font-mono bg-[var(--secondary)] text-[var(--warning)]">0/${{snap.total_routes}} 制限</span>`;
        const sub = ok > 0
          ? (site === 'Google Flights' ? '最安値＋通常価格レンジ＋LCC手荷物' : '実検索カード最安値を確認（通常価格表示なし）')
          : (siteFailReason[site] || '取得不可');
        return `
          <div class="p-2.5 rounded-lg border border-[var(--border)] bg-[var(--background)] space-y-1">
            <div class="flex items-center justify-between">
              <span class="text-xs font-semibold">${{esc(site)}}</span>
              ${{badge}}
            </div>
            <div class="text-xs text-[var(--muted-foreground)] leading-snug">${{esc(sub)}}</div>
          </div>
        `;
      }}).join('');

      // 5. Interactive 15-Route Table
      const q = (searchInput.value || '').trim().toLowerCase();
      const rf = regionFilter.value;
      const srt = sortSelect.value;

      let rows = DATA.routes.map((meta, idxOrder) => {{
        const cands = (obsByRoute[meta.code] || []).slice().sort((a, b) => approxJpy(a) - approxJpy(b));
        const best = cands[0] || null;
        const gfObs = (obsByRoute[meta.code] || []).find(o => o.source_site === 'Google Flights') || null;
        const primaryDiscObs = (best && best.discount_pct != null) ? best : gfObs;
        return {{ meta, idxOrder, best, cands, primaryDiscObs }};
      }});

      rows = rows.filter(r => {{
        if (rf === 'asia' && r.meta.region !== 'asia') return false;
        if (rf === 'long' && r.meta.region !== 'long') return false;
        if (rf === 'deals' && !(r.cands.some(c => c.is_deal_40_off))) return false;
        if (rf === 'lcc' && !(r.best && r.best.is_lcc)) return false;
        if (q) {{
          const hay = [
            r.meta.code,
            r.meta.city_ja,
            ...(r.cands.map(c => `${{c.airline}} ${{c.source_site}} ${{c.stops_text}}`))
          ].join(' ').toLowerCase();
          if (!hay.includes(q)) return false;
        }}
        return true;
      }});

      if (srt === 'discount') {{
        rows.sort((a, b) => ((b.primaryDiscObs?.discount_pct ?? -999) - (a.primaryDiscObs?.discount_pct ?? -999)));
      }} else if (srt === 'price') {{
        rows.sort((a, b) => approxJpy(a.best) - approxJpy(b.best));
      }} else if (srt === 'dep') {{
        rows.sort((a, b) => String(a.best?.dep_date || '9999').localeCompare(String(b.best?.dep_date || '9999')));
      }} else {{
        rows.sort((a, b) => a.idxOrder - b.idxOrder);
      }}

      document.getElementById('routeTableBody').innerHTML = rows.map(r => {{
        const b = r.best;
        if (!b) {{
          return `<tr><td class="py-3 px-2 font-mono font-semibold">${{esc(r.meta.code)}}（${{esc(r.meta.city_ja)}}）</td><td colspan="7" class="py-3 px-2 text-[var(--muted-foreground)]">実検索結果を取得できず</td></tr>`;
        }}
        const deltaHtml = (() => {{
          if (!(r.meta.code in prevBestJpy)) return '';
          const diff = Math.round(approxJpy(b) - prevBestJpy[r.meta.code]);
          if (Math.abs(diff) < 100) return '<div class="text-[var(--muted-foreground)]">前回比 ±0</div>';
          return diff < 0
            ? `<div class="text-[var(--success)] font-mono">▼ ¥${{Math.abs(diff).toLocaleString()}}</div>`
            : `<div class="text-[var(--error)] font-mono">▲ ¥${{diff.toLocaleString()}}</div>`;
        }})();

        const typCell = b.typical_price != null
          ? `<div class="font-mono tabular-nums">${{fmtMoney(b.typical_price, b.typical_currency)}}</div>` +
            (b.typical_low && b.typical_high ? `<div class="text-[var(--muted-foreground)] font-mono">${{fmtMoney(b.typical_low, b.typical_currency)}}〜${{fmtMoney(b.typical_high, b.typical_currency)}}</div>` : '')
          : (r.primaryDiscObs && r.primaryDiscObs !== b
              ? `<div class="text-[var(--muted-foreground)]">同サイト表示なし</div><div class="text-[var(--muted-foreground)] font-mono">※GF参考: ${{fmtMoney(r.primaryDiscObs.lowest_price, r.primaryDiscObs.currency)}} (-${{r.primaryDiscObs.discount_pct.toFixed(1)}}%)</div>`
              : `<span class="text-[var(--muted-foreground)]">同サイト表示なし</span>`);

        const discCell = b.discount_pct != null
          ? `<span class="px-2 py-0.5 rounded font-mono tabular-nums ${{b.is_deal_40_off ? 'font-bold text-[var(--success)] bg-[var(--secondary)]' : ''}}">${{b.discount_pct.toFixed(1)}}%</span>`
          : `<span class="text-[var(--muted-foreground)]">—</span>`;

        const others = r.cands.slice(1).map(c => `${{c.source_site}}: ${{fmtMoney(c.lowest_price, c.currency)}}`).join(' / ');

        return `
          <tr class="hover:bg-[var(--accent)] transition-colors align-top">
            <td class="py-3 px-2 whitespace-nowrap">
              <div class="font-mono font-bold">${{esc(r.meta.origin)}}→${{esc(r.meta.dest)}}</div>
              <div class="text-[var(--muted-foreground)]">${{esc(r.meta.city_ja)}}</div>
            </td>
            <td class="py-3 px-2 font-mono whitespace-nowrap">
              <div>${{fmtDateJa(b.dep_date)}}</div>
              <div class="text-[var(--muted-foreground)]">〜 ${{fmtDateJa(b.ret_date)}}</div>
            </td>
            <td class="py-3 px-2 whitespace-nowrap">
              <div class="font-mono font-bold tabular-nums">${{fmtMoney(b.lowest_price, b.currency)}}</div>
              <div class="text-[var(--muted-foreground)]">${{esc(b.tax_status)}}</div>
              ${{deltaHtml}}
            </td>
            <td class="py-3 px-2 whitespace-nowrap">${{typCell}}</td>
            <td class="py-3 px-2 whitespace-nowrap">${{discCell}}</td>
            <td class="py-3 px-2">
              <div class="font-medium">${{esc(b.airline)}}</div>
              <div class="text-[var(--muted-foreground)]">${{esc(b.stops_text)}}${{b.checked_baggage ? ' ／ ' + esc(b.checked_baggage) : ''}}</div>
            </td>
            <td class="py-3 px-2">
              <div class="font-semibold">${{esc(b.source_site)}}</div>
              ${{others ? `<div class="text-[var(--muted-foreground)] mt-0.5">${{esc(others)}}</div>` : ''}}
            </td>
            <td class="py-3 px-2 text-right whitespace-nowrap">
              <a href="${{esc(b.search_url)}}" target="_blank" rel="noopener noreferrer" class="font-semibold text-[var(--link)] hover:underline">開く ↗</a>
            </td>
          </tr>
        `;
      }}).join('');
    }}

    init();
  </script>
</body>
</html>
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build interactive HTML dashboard from JSON snapshots.")
    parser.add_argument(
        "--snapshots-dir",
        required=True,
        help="Directory containing daily YYYY-MM-DD.json snapshot files.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output HTML file path.",
    )
    parser.add_argument(
        "--mode",
        choices=("standalone", "artifact"),
        default="standalone",
        help="Output theming mode (default: standalone).",
    )
    args = parser.parse_args(argv)

    snaps = load_snapshots(Path(args.snapshots_dir).expanduser().resolve())
    html_str = build_dashboard_html(snaps, mode=args.mode)
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_str, encoding="utf-8")
    print(f"[dashboard] Wrote {args.mode} dashboard ({len(snaps)} snapshot(s)) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
