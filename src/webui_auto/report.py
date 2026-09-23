"""报告：卡片式 HTML（彩色仪表盘 + 状态图标 + 失败原因标红）以及 JSON / JUnit 输出。"""
from __future__ import annotations

import html
import json
import os
from typing import Any, Dict, List

_ICON = {"pass": "✓", "fail": "✗", "error": "⚠"}
_STEP_ICON = {"ok": "✓", "fail": "✗", "error": "⚠", "skipped": "⊘"}


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _failure_reason(r: Dict[str, Any]) -> str:
    """从 error / 首个失败 step / 首个失败 assertion 提炼一句话原因。"""
    if r.get("error"):
        return str(r["error"])
    for st in r.get("steps") or []:
        if st.get("status") in ("fail", "error"):
            return f"步骤「{st.get('action')}」{st.get('status')}：{st.get('detail')}"
    for a in r.get("assertions") or []:
        if not a.get("ok"):
            return (f"断言「{a.get('type')}」不通过：期望 {a.get('expected')}，"
                    f"实际 {a.get('actual')}｜{a.get('detail')}")
    return ""


def _steps_html(steps: List[Dict[str, Any]]) -> str:
    if not steps:
        return "<div class='empty'>（无操作）</div>"
    rows = []
    for i, st in enumerate(steps, 1):
        status = str(st.get("status", "ok"))
        icon = _STEP_ICON.get(status, "•")
        cls = {"ok": "ok", "skipped": "skipped"}.get(status, "bad")
        rows.append(
            f"<div class='item {cls}'>"
            f"<span class='ic'>{icon}</span>"
            f"<span class='no'>{i}</span>"
            f"<span class='act'>{_e(st.get('action'))}</span>"
            f"<span class='det'>{_e(st.get('detail'))}</span>"
            f"<span class='ms'>{st.get('elapsed', '')}s</span>"
            f"</div>"
        )
    return "".join(rows)


def _assertions_html(assertions: List[Dict[str, Any]]) -> str:
    if not assertions:
        return "<div class='empty'>（无断言）</div>"
    rows = []
    for a in assertions:
        ok = bool(a.get("ok"))
        icon = _ICON["pass"] if ok else _ICON["fail"]
        cls = "ok" if ok else "bad"
        rows.append(
            f"<div class='item {cls}'>"
            f"<span class='ic'>{icon}</span>"
            f"<span class='act'>{_e(a.get('type'))}</span>"
            f"<span class='det'>"
            f"实际：<b>{_e(a.get('actual'))}</b> ｜ 期望：<b>{_e(a.get('expected'))}</b>"
            f"<br><span class='sub'>{_e(a.get('detail'))}</span>"
            f"</span>"
            f"<span class='ms'>{a.get('elapsed', '')}s</span>"
            f"</div>"
        )
    return "".join(rows)


def _case_blocks(results: List[Dict[str, Any]]) -> str:
    blocks = []
    for r in results:
        status = str(r.get("status", "pass"))
        icon = _ICON.get(status, "•")
        reason = _failure_reason(r)
        reason_html = (f"<div class='reason'><b>失败原因：</b>{_e(reason)}</div>" if reason else "")
        blocks.append(
            f"<div class='case {status}' data-status='{status}'>"
            f"<div class='casehead'>"
            f"<span class='badge {status}'>{icon} {status.upper()}</span>"
            f"<span class='cid'>{_e(r.get('id'))}</span>"
            f"<span class='cname'>{_e(r.get('name'))}</span>"
            f"<span class='ms'>{r.get('elapsed', '')}s</span>"
            f"</div>"
            f"{reason_html}"
            f"<div class='sec'><div class='sectitle'>操作（{len(r.get('steps') or [])}）</div>"
            f"<div class='timeline'>{_steps_html(r.get('steps'))}</div></div>"
            f"<div class='sec'><div class='sectitle'>断言（{len(r.get('assertions') or [])}）</div>"
            f"<div class='timeline'>{_assertions_html(r.get('assertions'))}</div></div>"
            f"</div>"
        )
    return "".join(blocks)


CSS = """
*{box-sizing:border-box}
body{margin:0;padding:24px;background:#f5f7fa;color:#1f2937;
 font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;font-size:14px}
h1{font-size:20px;margin:0 0 4px}
.meta{color:#6b7280;font-size:12px;margin-bottom:16px}
.dash{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.card{background:#fff;border-radius:10px;padding:14px 18px;min-width:120px;
 box-shadow:0 1px 3px rgba(0,0,0,.08);border-top:4px solid #3b82f6}
.card span{display:block;font-size:12px;color:#6b7280}
.card b{font-size:22px}
.card.pass{border-top-color:#16a34a}.card.fail{border-top-color:#dc2626}
.card.error{border-top-color:#f59e0b}.card.rate{border-top-color:#2563eb}
.toolbar{margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap}
.toolbar button{border:1px solid #d1d5db;background:#fff;border-radius:6px;
 padding:6px 12px;cursor:pointer;font-size:13px}
.toolbar button:hover{background:#eef2ff}
.case{background:#fff;border-radius:10px;padding:14px;margin-bottom:12px;
 box-shadow:0 1px 3px rgba(0,0,0,.08);border-left:5px solid #16a34a}
.case.fail{border-left-color:#dc2626}.case.error{border-left-color:#f59e0b}
.casehead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.badge{padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;color:#fff}
.badge.pass{background:#16a34a}.badge.fail{background:#dc2626}.badge.error{background:#f59e0b}
.cid{font-family:monospace;color:#6b7280}.cname{font-weight:600}
.ms{margin-left:auto;color:#9ca3af;font-size:12px}
.reason{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;
 border-radius:6px;padding:8px 10px;margin-bottom:10px;font-size:13px}
.sec{margin-top:8px}
.sectitle{font-size:12px;color:#4b5563;margin-bottom:6px;font-weight:600}
.timeline{border:1px solid #e5e7eb;border-radius:6px;overflow:hidden}
.item{display:flex;gap:8px;align-items:flex-start;padding:7px 10px;
 border-bottom:1px solid #f3f4f6;font-size:13px}
.item:last-child{border-bottom:none}
.item.ok .ic{color:#16a34a}.item.bad{background:#fef2f2}
.item.bad .ic{color:#dc2626}.item.skipped .ic{color:#9ca3af}
.ic{width:16px;text-align:center;font-weight:700}
.no{color:#9ca3af;font-size:12px;min-width:18px}
.act{font-weight:600;min-width:70px}
.det{flex:1;color:#374151;word-break:break-all}
.det .sub{color:#6b7280;font-size:12px}
.empty{color:#9ca3af;padding:6px 10px;font-size:12px}
"""


def to_html(report: Dict[str, Any]) -> str:
    s = report.get("summary") or {}
    meta = report.get("meta") or {}
    results = report.get("results") or []
    rate = s.get("rate", 0)
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>UI 自动化测试报告</title><style>{CSS}</style></head><body>
<h1>UI 自动化测试报告</h1>
<div class="meta">站点：{_e(meta.get('base_url'))} ｜ profile：{_e(meta.get('profile'))}
 ｜ 时间：{_e(meta.get('started'))} ｜ 浏览器：{_e(meta.get('browser'))}</div>
<div class="dash">
<div class="card"><span>总用例</span><b>{s.get('total', 0)}</b></div>
<div class="card pass"><span>通过</span><b>{s.get('pass', 0)}</b></div>
<div class="card fail"><span>失败</span><b>{s.get('fail', 0)}</b></div>
<div class="card error"><span>异常</span><b>{s.get('error', 0)}</b></div>
<div class="card rate"><span>通过率</span><b>{rate}%</b></div>
</div>
<div class="toolbar">
<button onclick="setFilter('all')">全部</button>
<button onclick="setFilter('fail')">🔍 仅看失败</button>
<button onclick="toggleAll()">⊞ 展开/收起全部</button>
</div>
<div id="caselist">{_case_blocks(results)}</div>
<script>
function setFilter(f){{
  var cs=document.querySelectorAll('.case');
  for(var i=0;i<cs.length;i++){{
    var st=cs[i].getAttribute('data-status');
    cs[i].style.display=(f==='all'||st==='fail'||st==='error')?'':'none';
  }}
}}
function toggleAll(){{
  var ts=document.querySelectorAll('.timeline');
  var anyHidden=false;
  for(var i=0;i<ts.length;i++){{ if(ts[i].style.display==='none') anyHidden=true; }}
  for(var j=0;j<ts.length;j++){{ ts[j].style.display=anyHidden?'':'none'; }}
}}
</script></body></html>"""


def write_report(report: Dict[str, Any], out_dir: str = "reports") -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    ts = (report.get("meta") or {}).get("stamp") or "run"
    html_path = os.path.join(out_dir, f"cases_{ts}.html")
    json_path = os.path.join(out_dir, f"cases_{ts}.json")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(to_html(report))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return {"html": html_path, "json": json_path}


def write_junit(report: Dict[str, Any], out_dir: str = "reports") -> str:
    os.makedirs(out_dir, exist_ok=True)
    ts = (report.get("meta") or {}).get("stamp") or "run"
    path = os.path.join(out_dir, f"junit_{ts}.xml")
    results = report.get("results") or []
    s = report.get("summary") or {}
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="webui-auto" tests="{s.get("total",0)}" '
        f'failures="{s.get("fail",0)}" errors="{s.get("error",0)}" '
        f'time="{s.get("elapsed",0)}">',
    ]
    for r in results:
        lines.append(f'<testcase classname="webui-auto" name="{_e(r.get("id"))}-{_e(r.get("name"))}" '
                     f'time="{r.get("elapsed",0)}">')
        if r.get("status") == "fail":
            lines.append(f'<failure message="{_e(_failure_reason(r))}">'
                         f'{_e(_failure_reason(r))}</failure>')
        elif r.get("status") == "error":
            lines.append(f'<error message="{_e(_failure_reason(r))}">'
                         f'{_e(_failure_reason(r))}</error>')
        lines.append("</testcase>")
    lines.append("</testsuite>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
