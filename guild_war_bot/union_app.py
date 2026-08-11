from __future__ import annotations

import argparse
import html
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .union_suite import (
    DEFAULT_DB_PATH,
    ROOT,
    UnionRaidSuite,
    format_hp,
    format_number,
    normalize_date_value,
    parse_int_text,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8792
PYTHON_EXE = Path(sys.executable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NIKKE 联盟突袭管理台")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args(argv)

    suite = UnionRaidSuite(args.db)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(suite))
    print(f"NIKKE 联盟突袭管理台：http://{args.host}:{args.port}/")
    print(f"数据文件：{suite.db_path}")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        suite.close()
    return 0


def build_handler(suite: UnionRaidSuite) -> type[BaseHTTPRequestHandler]:
    class UnionAppHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            notice = (query.get("notice") or [""])[0]
            if path == "/artifact":
                self.send_artifact((query.get("path") or [""])[0])
                return
            if path != "/":
                self.send_response(404)
                self.end_headers()
                return
            self.send_html(render_page(suite, notice, (query.get("battle_date") or [""])[0]))

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = urllib.parse.parse_qs(raw)
            action = form_value(form, "action")

            try:
                if action == "add_member":
                    notice = suite.add_member(
                        form_value(form, "name"),
                        form_value(form, "server_area") or None,
                        form_value(form, "qq") or None,
                        form_value(form, "group_card") or None,
                    )
                elif action == "bulk_update_members":
                    notice = suite.update_members(member_rows_from_form(form))
                elif action == "import_sampled_members":
                    notice = suite.import_sampled_members(
                        limit=int(form_value(form, "limit") or "32"),
                        server_area=form_value(form, "server_area") or None,
                    )
                elif action == "add_boss_snapshot":
                    notice = suite.add_boss_snapshot(
                        raid_day=parse_int_text(form_value(form, "raid_day")),
                        boss_index=parse_int_text(form_value(form, "boss_index")),
                        boss_label=form_value(form, "boss_label"),
                        boss_name=form_value(form, "boss_name"),
                        level=parse_int_text(form_value(form, "level")),
                        current_hp=parse_int_text(form_value(form, "current_hp")),
                        total_hp=parse_int_text(form_value(form, "total_hp")),
                        image_path=form_value(form, "image_path"),
                        note=form_value(form, "note"),
                    )
                elif action == "add_attack":
                    notice = suite.add_attack(
                        member_id=int(form_value(form, "member_id") or "0"),
                        battle_date_text=form_value(form, "battle_date"),
                        damage=parse_int_text(form_value(form, "damage")),
                        note=form_value(form, "note"),
                        boss_label=form_value(form, "boss_label"),
                        boss_name=form_value(form, "boss_name"),
                        team_text=form_value(form, "team_text"),
                        raid_day=parse_int_text(form_value(form, "raid_day")),
                        is_tail=form_value(form, "is_tail") == "1",
                    )
                elif action == "delete_attack":
                    notice = suite.delete_attack(int(form_value(form, "attack_id") or "0"))
                elif action == "task_member_scan":
                    notice = suite.start_command_task(
                        "member_scan",
                        "队员信息自动采样",
                        [
                            str(PYTHON_EXE),
                            "union_auto_sampler.py",
                            "scan-game",
                            "--pages",
                            form_value(form, "pages") or "12",
                        ],
                    )
                elif action == "task_member_assist":
                    notice = suite.start_command_task(
                        "member_assist_scan",
                        "队员信息半自动采样",
                        [
                            str(PYTHON_EXE),
                            "union_auto_sampler.py",
                            "assist-scan",
                            "--pages",
                            form_value(form, "pages") or "20",
                            "--interval",
                            form_value(form, "interval") or "5",
                        ],
                    )
                elif action == "task_progress_capture":
                    notice = suite.start_command_task(
                        "progress_capture",
                        "联盟突袭进度截图",
                        [str(PYTHON_EXE), "game_progress_query.py", "run"],
                    )
                elif action == "task_flow1_scan":
                    flow1_values = flow1_settings_from_form(form)
                    suite.save_flow1_settings(flow1_values)
                    cmd = [
                        "cmd.exe",
                        "/c",
                        "start",
                        "NIKKE Flow1 Sampler",
                        str(ROOT / "start-flow1-sampler-visible.bat"),
                        "-RaidDay",
                        flow1_values["flow1_raid_day"],
                        "-BattleDate",
                        flow1_values["flow1_battle_date"],
                        "-Pages",
                        flow1_values["flow1_pages"],
                        "-ScrollRows",
                        flow1_values["flow1_scroll_rows"],
                        "-DragStartRow",
                        flow1_values["flow1_drag_start_row"],
                        "-DragDistanceRows",
                        flow1_values["flow1_drag_distance_rows"],
                        "-DragEndSafeRatio",
                        flow1_values["flow1_drag_end_safe_ratio"],
                        "-DragAnchorStart",
                        flow1_values["flow1_drag_anchor_start"],
                        "-DragAnchorEnd",
                        flow1_values["flow1_drag_anchor_end"],
                        "-UnionPoint",
                        flow1_values["flow1_union_point"],
                        "-RaidEntryPoint",
                        flow1_values["flow1_raid_entry_point"],
                        "-DayTabPoint",
                        flow1_values["flow1_day_tab_point"],
                        "-Day1Point",
                        flow1_values["flow1_day1_point"],
                        "-Day2Point",
                        flow1_values["flow1_day2_point"],
                        "-DragDurationSeconds",
                        flow1_values["flow1_drag_duration_seconds"],
                        "-DragSteps",
                        flow1_values["flow1_drag_steps"],
                        "-DragHoldSeconds",
                        flow1_values["flow1_drag_hold_seconds"],
                    ]
                    if flow1_values["flow1_use_drag_anchor"] == "1":
                        cmd.append("-UseDragAnchor")
                    if flow1_values["flow1_record_point"]:
                        cmd.extend(["-RecordPoint", flow1_values["flow1_record_point"]])
                    if flow1_values["flow1_skip_open_record"] == "1":
                        cmd.append("-SkipOpenRecord")
                    notice = suite.start_command_task(
                        "flow1_day_scan",
                        "流程1出刀明细可视采样",
                        cmd,
                    )
                elif action == "task_flow1_calibrate":
                    flow1_values = flow1_settings_from_form(form)
                    suite.save_flow1_settings(flow1_values)
                    notice = suite.start_command_task(
                        "flow1_calibrate",
                        "流程1参数校准向导",
                        [
                            "cmd.exe",
                            "/c",
                            "start",
                            "NIKKE Flow1 Calibrate",
                            str(ROOT / "start-flow1-calibrate-visible.bat"),
                            "-DragDurationSeconds",
                            flow1_values["flow1_drag_duration_seconds"],
                            "-DragSteps",
                            flow1_values["flow1_drag_steps"],
                            "-DragHoldSeconds",
                            flow1_values["flow1_drag_hold_seconds"],
                        ],
                    )
                elif action == "save_flow1_settings":
                    notice = suite.save_flow1_settings(flow1_settings_from_form(form))
                elif action == "export_workbook":
                    path = suite.export_workbook()
                    notice = f"已导出：{path}"
                elif action == "export_day_workbook":
                    path = suite.export_day_workbook(form_value(form, "battle_date"))
                    notice = f"已导出当天表格：{path}"
                else:
                    notice = "未知操作。"
            except Exception as exc:
                notice = f"操作失败：{type(exc).__name__}: {exc}"

            redirect_date = form_value(form, "view_date") or form_value(form, "battle_date")
            location = f"/?notice={urllib.parse.quote(notice)}"
            if redirect_date:
                location += f"&battle_date={urllib.parse.quote(redirect_date)}"
            self.redirect(location)

        def send_html(self, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_artifact(self, raw_path: str) -> None:
            if not raw_path:
                self.send_response(404)
                self.end_headers()
                return
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            allowed_roots = [
                ROOT.resolve(),
                Path(os.environ.get("TEMP", "")).resolve(),
                Path(r"D:\Codex\依赖").resolve(),
            ]
            resolved = path.resolve()
            if not any(is_relative_to(resolved, root) for root in allowed_roots):
                self.send_response(403)
                self.end_headers()
                return
            data = resolved.read_bytes()
            content_type = "application/octet-stream"
            if resolved.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                content_type = f"image/{'jpeg' if resolved.suffix.lower() in {'.jpg', '.jpeg'} else 'png'}"
            elif resolved.suffix.lower() == ".xlsx":
                content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif resolved.suffix.lower() == ".csv":
                content_type = "text/csv; charset=utf-8"
            elif resolved.suffix.lower() == ".json":
                content_type = "application/json; charset=utf-8"
            elif resolved.suffix.lower() in {".log", ".txt"}:
                content_type = "text/plain; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if resolved.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                filename = urllib.parse.quote(resolved.name)
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{filename}")
            self.end_headers()
            self.wfile.write(data)

        def redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[UnionApp] {self.address_string()} - {fmt % args}")

    return UnionAppHandler


def render_page(suite: UnionRaidSuite, notice: str = "", battle_date_filter: str = "") -> str:
    dashboard = suite.dashboard()
    flow1_settings = suite.flow1_settings()
    selected_day = (
        normalize_date_value(battle_date_filter)
        or normalize_date_value(flow1_settings.get("flow1_battle_date"))
        or str(dashboard["battle_date"])
    )
    flow1_settings["flow1_battle_date"] = selected_day
    members = suite.list_members()
    member_options = "\n".join(
        f'<option value="{member.id}">{escape(member.name)}'
        f'{(" / " + escape(member.server_area)) if member.server_area else ""}</option>'
        for member in members
        if member.active
    )
    member_rows = "\n".join(render_member_row(member) for member in members)
    snapshot_rows = "\n".join(render_snapshot_row(row) for row in suite.list_boss_snapshots())
    attack_rows = "\n".join(render_attack_row(row) for row in suite.list_attacks())
    day_summary = suite.attendance_rows_for_date(selected_day)
    day_summary_rows = "\n".join(render_day_summary_row(row) for row in day_summary)
    day_attacks = suite.list_attacks(limit=500, battle_date=selected_day, newest_first=False)
    day_attack_rows = "\n".join(render_attack_row(row, selected_day) for row in day_attacks)
    task_rows = "\n".join(render_task_row(row) for row in suite.list_tasks())
    samples = suite.latest_sample_members(8)
    sample_rows = "\n".join(render_sample_row(row) for row in samples)
    flow1_artifact_rows = "\n".join(
        render_flow1_artifact_row(row) for row in suite.latest_flow1_artifacts()
    )
    flow1_anchor_checked = "checked" if flow1_settings.get("flow1_use_drag_anchor") == "1" else ""
    flow1_skip_checked = "checked" if flow1_settings.get("flow1_skip_open_record") == "1" else ""
    notice_html = f'<div class="notice">{escape(notice)}</div>' if notice else ""
    latest_snapshot = dashboard["latest_snapshot"]
    latest_snapshot_text = (
        f"{escape(latest_snapshot.captured_at)} {escape(latest_snapshot.boss_label or '-')}"
        f" {escape(latest_snapshot.boss_name or '')} {escape(format_hp(latest_snapshot.current_hp, latest_snapshot.total_hp, latest_snapshot.percent))}"
        if latest_snapshot
        else "暂无"
    )
    latest_task = dashboard["latest_task"]
    latest_task_text = (
        f"{escape(latest_task.title)} / {escape(latest_task.status)} / {escape(latest_task.started_at)}"
        if latest_task
        else "暂无"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NIKKE 联盟突袭管理台</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --panel-2: #f8fafc;
      --line: #d8dee8;
      --text: #182033;
      --muted: #667085;
      --primary: #1166d8;
      --primary-soft: #e8f1ff;
      --danger: #bf3030;
      --ok: #24733c;
      --warn: #9a5b00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Microsoft YaHei", "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1360px; margin: 0 auto; padding: 18px; }}
    header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }}
    h1 {{ margin: 0 0 4px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    h3 {{ margin: 0 0 8px; font-size: 14px; color: var(--muted); }}
    .sub {{ color: var(--muted); }}
    .notice {{
      margin-bottom: 14px;
      padding: 10px 12px;
      border: 1px solid #afd7bb;
      border-radius: 6px;
      background: #eef9f1;
      color: var(--ok);
      overflow-wrap: anywhere;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 86px;
    }}
    .kpi .label {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .kpi .value {{ font-size: 22px; font-weight: 700; }}
    .kpi .extra {{ color: var(--muted); margin-top: 6px; overflow-wrap: anywhere; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 14px;
    }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .grid-3 {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr)) auto;
      gap: 9px;
      align-items: end;
    }}
    .form-grid.attack {{ grid-template-columns: 1.1fr .8fr .8fr .8fr 1fr 1fr .7fr auto; }}
    label {{ display: grid; gap: 5px; color: var(--muted); font-size: 12px; }}
    input, select, textarea {{
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 9px;
      color: var(--text);
      background: #fff;
      font: inherit;
    }}
    textarea {{ min-height: 92px; resize: vertical; font-family: Consolas, "Microsoft YaHei", monospace; }}
    button, .button {{
      min-height: 36px;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 7px 12px;
      background: var(--primary);
      color: #fff;
      font: inherit;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }}
    button.secondary, .button.secondary {{ background: #fff; color: var(--primary); border-color: var(--primary); }}
    button.danger {{ background: #fff; color: var(--danger); border-color: #e0b2b2; }}
    .task-buttons {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .inline {{ display: flex; gap: 8px; align-items: end; flex-wrap: wrap; }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }}
    .section-actions {{ display: flex; gap: 8px; align-items: end; flex-wrap: wrap; }}
    .muted {{ color: var(--muted); }}
    .path-text {{ font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px 7px;
      text-align: left;
      vertical-align: middle;
      overflow-wrap: anywhere;
    }}
    th {{ color: var(--muted); background: var(--panel-2); font-size: 12px; font-weight: 600; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .status-running {{ color: var(--warn); font-weight: 700; }}
    .status-success {{ color: var(--ok); font-weight: 700; }}
    .status-failed {{ color: var(--danger); font-weight: 700; }}
    .member-grid {{
      display: grid;
      grid-template-columns: 54px 95px 1fr 130px 1.2fr 92px;
      gap: 8px;
      align-items: center;
      padding: 7px 0;
      border-bottom: 1px solid var(--line);
    }}
    .member-grid.header {{ color: var(--muted); background: var(--panel-2); padding: 8px; font-size: 12px; font-weight: 600; }}
    .empty {{ padding: 18px; color: var(--muted); text-align: center; }}
    .artifact-img {{ max-width: 180px; max-height: 86px; object-fit: contain; border: 1px solid var(--line); border-radius: 6px; }}
    @media (max-width: 1040px) {{
      .kpis, .grid-2, .grid-3, .form-grid, .form-grid.attack {{ grid-template-columns: 1fr; }}
      .member-grid {{ grid-template-columns: 1fr; }}
      table, thead, tbody, tr, td {{ display: block; width: 100%; }}
      thead {{ display: none; }}
      tr {{ border-bottom: 1px solid var(--line); padding: 8px 0; }}
      td {{ border: 0; padding: 5px 0; }}
      .num {{ text-align: left; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>NIKKE 联盟突袭管理台</h1>
      <div class="sub">统一入口：成员绑定、进度采样、出刀统计、质量记录、Excel 导出。</div>
    </div>
    <form method="post">
      <input type="hidden" name="action" value="export_workbook">
      <button type="submit">导出 Excel</button>
    </form>
  </header>
  {notice_html}

  <div class="kpis">
    <div class="kpi"><div class="label">战斗日</div><div class="value">{escape(str(dashboard["battle_date"]))}</div><div class="extra">每日 04:00 切日</div></div>
    <div class="kpi"><div class="label">成员</div><div class="value">{dashboard["members_active"]}/{dashboard["members_total"]}</div><div class="extra">启用/全部</div></div>
    <div class="kpi"><div class="label">今日出刀</div><div class="value">{dashboard["attacks_done"]}/{dashboard["attacks_required"]}</div><div class="extra">基于当前成员绑定</div></div>
    <div class="kpi"><div class="label">最新 Boss</div><div class="extra">{latest_snapshot_text}</div></div>
    <div class="kpi"><div class="label">最近任务</div><div class="extra">{latest_task_text}</div></div>
  </div>

  <section>
    <h2>采样任务</h2>
    <div class="grid-3">
      <form method="post">
        <input type="hidden" name="action" value="task_progress_capture">
        <h3>Boss 进度截图</h3>
        <p class="muted">调用已有 <code>game_progress_query.py run</code>，进入联盟突袭并保存 Boss 血量截图。</p>
        <button type="submit">开始截图采样</button>
      </form>
      <form method="post">
        <input type="hidden" name="action" value="task_member_scan">
        <h3>队员自动采样</h3>
        <label>页数<input name="pages" value="12" inputmode="numeric"></label>
        <button type="submit" style="margin-top:8px;">开始自动采样</button>
      </form>
      <form method="post">
        <input type="hidden" name="action" value="task_member_assist">
        <h3>队员半自动采样</h3>
        <div class="inline">
          <label>页数<input name="pages" value="20" inputmode="numeric"></label>
          <label>间隔秒<input name="interval" value="5" inputmode="numeric"></label>
        </div>
        <button type="submit" style="margin-top:8px;">开始半自动采样</button>
      </form>
      <form method="post">
        <input type="hidden" name="view_date" value="{escape(selected_day)}">
        <h3>流程1出刀明细</h3>
        <div class="inline">
          <label>Day<input name="raid_day" value="{escape(flow1_settings["flow1_raid_day"])}" inputmode="numeric"></label>
          <label>日期<input type="date" name="battle_date" value="{escape(flow1_settings["flow1_battle_date"])}"></label>
          <label>页数<input name="pages" value="{escape(flow1_settings["flow1_pages"])}" inputmode="numeric"></label>
          <label>每屏记录<input name="scroll_rows" value="{escape(flow1_settings["flow1_scroll_rows"])}" inputmode="numeric"></label>
          <label>拖动行<input name="drag_start_row" value="{escape(flow1_settings["flow1_drag_start_row"])}" inputmode="numeric"></label>
          <label>拖动距离<input name="drag_distance_rows" value="{escape(flow1_settings["flow1_drag_distance_rows"])}" inputmode="decimal"></label>
          <label>终点比例<input name="drag_end_safe_ratio" value="{escape(flow1_settings["flow1_drag_end_safe_ratio"])}" inputmode="decimal"></label>
          <label><input type="checkbox" name="use_drag_anchor" value="1" {flow1_anchor_checked}>锚点拖动</label>
          <label>起点锚点<input name="drag_anchor_start" value="{escape(flow1_settings["flow1_drag_anchor_start"])}" inputmode="decimal"></label>
          <label>终点锚点<input name="drag_anchor_end" value="{escape(flow1_settings["flow1_drag_anchor_end"])}" inputmode="decimal"></label>
          <label>联盟入口<input name="union_point" value="{escape(flow1_settings["flow1_union_point"])}" inputmode="decimal"></label>
          <label>突袭入口<input name="raid_entry_point" value="{escape(flow1_settings["flow1_raid_entry_point"])}" inputmode="decimal"></label>
          <label>记录入口<input name="record_point" value="{escape(flow1_settings["flow1_record_point"])}" inputmode="decimal"></label>
          <label>按天按钮<input name="day_tab_point" value="{escape(flow1_settings["flow1_day_tab_point"])}" inputmode="decimal"></label>
          <label>第1天<input name="day1_point" value="{escape(flow1_settings["flow1_day1_point"])}" inputmode="decimal"></label>
          <label>第2天<input name="day2_point" value="{escape(flow1_settings["flow1_day2_point"])}" inputmode="decimal"></label>
          <label>拖动耗时<input name="drag_duration_seconds" value="{escape(flow1_settings["flow1_drag_duration_seconds"])}" inputmode="decimal"></label>
          <label>拖动步数<input name="drag_steps" value="{escape(flow1_settings["flow1_drag_steps"])}" inputmode="numeric"></label>
          <label>松手延迟<input name="drag_hold_seconds" value="{escape(flow1_settings["flow1_drag_hold_seconds"])}" inputmode="decimal"></label>
          <label><input type="checkbox" name="skip_open_record" value="1" {flow1_skip_checked}>已打开记录</label>
        </div>
        <div class="task-buttons" style="margin-top:8px;">
          <button type="submit" name="action" value="task_flow1_scan">打开可视采样窗口</button>
          <button class="secondary" type="submit" name="action" value="task_flow1_calibrate">参数校准向导</button>
          <button class="secondary" type="submit" name="action" value="save_flow1_settings">保存参数</button>
        </div>
        <p class="muted">当前稳定拖动参数会保存到后台；采样结束后，下面的文件会自动刷新为最新识别结果。</p>
        <table style="margin-top:8px;">
          <thead><tr><th>文件</th><th>状态</th><th>路径/下载</th></tr></thead>
          <tbody>{flow1_artifact_rows if flow1_artifact_rows else '<tr><td class="empty" colspan="3">暂无流程1识别产物</td></tr>'}</tbody>
        </table>
      </form>
    </div>
  </section>

  <section>
    <div class="section-head">
      <div>
        <h2>按日期查看出刀</h2>
        <div class="sub">当前日期：{escape(selected_day)}。第一天有人 0/1 刀属于正常情况，这里只做统计展示。</div>
      </div>
      <div class="section-actions">
        <form method="get" class="inline">
          <label>日期<input type="date" name="battle_date" value="{escape(selected_day)}"></label>
          <button class="secondary" type="submit">查看</button>
        </form>
        <form method="post" class="inline">
          <input type="hidden" name="action" value="export_day_workbook">
          <input type="hidden" name="battle_date" value="{escape(selected_day)}">
          <input type="hidden" name="view_date" value="{escape(selected_day)}">
          <button type="submit">导出当天表格</button>
        </form>
      </div>
    </div>
    <table>
      <thead><tr><th>成员ID</th><th>区服</th><th class="num">出刀</th><th class="num">第一刀</th><th class="num">第二刀</th><th class="num">第三刀</th><th class="num">总伤害</th><th class="num">占比</th><th class="num">剩余</th><th>备注</th></tr></thead>
      <tbody>{day_summary_rows if day_summary_rows else '<tr><td class="empty" colspan="10">暂无成员名单</td></tr>'}</tbody>
    </table>
    <h3 style="margin-top:14px;">当天出刀明细</h3>
    <table>
      <thead><tr><th>日期</th><th>成员</th><th>刀</th><th>Boss</th><th>伤害</th><th>阵容</th><th>尾刀</th><th>备注</th><th>操作</th></tr></thead>
      <tbody>{day_attack_rows if day_attack_rows else '<tr><td class="empty" colspan="9">这一天还没有入库的出刀记录</td></tr>'}</tbody>
    </table>
  </section>

  <section class="grid-2">
    <div>
      <h2>成员绑定</h2>
      <form class="form-grid" method="post">
        <input type="hidden" name="action" value="add_member">
        <label>游戏名<input name="name" required placeholder="DORO"></label>
        <label>区服<input name="server_area" placeholder="Q区 / V区"></label>
        <label>QQ号<input name="qq" inputmode="numeric"></label>
        <label>群名片<input name="group_card" placeholder="〔Q区〕DORO"></label>
        <button type="submit">新增</button>
      </form>
      <form method="post" style="margin-top:12px;">
        <input type="hidden" name="action" value="bulk_update_members">
        <div class="member-grid header"><div>ID</div><div>区服</div><div>游戏名</div><div>QQ号</div><div>群名片</div><div>状态</div></div>
        {member_rows if member_rows else '<div class="empty">暂无成员</div>'}
        <button type="submit" style="margin-top:10px;">保存成员修改</button>
      </form>
    </div>
    <div>
      <h2>采样成员同步</h2>
      <p class="muted">当前队员采样库中有 {dashboard["sample_count"]} 条记录。这里会把最新采样名同步到成员绑定库，QQ 号仍需要后续人工绑定。</p>
      <form method="post" class="inline">
        <input type="hidden" name="action" value="import_sampled_members">
        <label>导入人数<input name="limit" value="32" inputmode="numeric"></label>
        <label>默认区服<input name="server_area" placeholder="Q区 / V区"></label>
        <button type="submit">同步采样成员</button>
      </form>
      <table style="margin-top:12px;">
        <thead><tr><th>采样名</th><th class="num">战力</th><th class="num">等级</th><th>在线</th></tr></thead>
        <tbody>{sample_rows if sample_rows else '<tr><td class="empty" colspan="4">暂无采样预览</td></tr>'}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>手动校对 Boss 进度</h2>
    <form class="form-grid" method="post">
      <input type="hidden" name="action" value="add_boss_snapshot">
      <label>Day<input name="raid_day" placeholder="1"></label>
      <label>Boss<input name="boss_label" placeholder="I / II / III"></label>
      <label>Boss名<input name="boss_name" placeholder="殓巾"></label>
      <label>等级<input name="level" placeholder="10"></label>
      <label>当前血量<input name="current_hp" placeholder="1,677,989,700"></label>
      <label>总血量<input name="total_hp" placeholder="1,677,989,700"></label>
      <label>截图路径<input name="image_path" placeholder="D:\\...\\boss.png"></label>
      <label>备注<input name="note"></label>
      <button type="submit">保存</button>
    </form>
    <table style="margin-top:12px;">
      <thead><tr><th>时间</th><th>Day</th><th>Boss</th><th>名称</th><th>等级</th><th>血量</th><th>截图</th><th>备注</th></tr></thead>
      <tbody>{snapshot_rows if snapshot_rows else '<tr><td class="empty" colspan="8">暂无 Boss 快照</td></tr>'}</tbody>
    </table>
  </section>

  <section>
    <h2>出刀质量记录</h2>
    <form class="form-grid attack" method="post">
      <input type="hidden" name="action" value="add_attack">
      <input type="hidden" name="view_date" value="{escape(selected_day)}">
      <label>成员<select name="member_id" required>{member_options}</select></label>
      <label>日期<input type="date" name="battle_date" value="{escape(selected_day)}"></label>
      <label>Day<input name="raid_day" placeholder="1"></label>
      <label>伤害<input name="damage" placeholder="12.3亿 / 1230000000"></label>
      <label>Boss<input name="boss_label" placeholder="I"></label>
      <label>Boss名<input name="boss_name" placeholder="殓巾"></label>
      <label>阵容<input name="team_text" placeholder="丽塔 / 皇冠 / ..."></label>
      <label>尾刀<select name="is_tail"><option value="0">否</option><option value="1">是</option></select></label>
      <button type="submit">记录</button>
    </form>
    <table style="margin-top:12px;">
      <thead><tr><th>日期</th><th>成员</th><th>刀</th><th>Boss</th><th>伤害</th><th>阵容</th><th>尾刀</th><th>备注</th><th>操作</th></tr></thead>
      <tbody>{attack_rows if attack_rows else '<tr><td class="empty" colspan="9">暂无出刀记录</td></tr>'}</tbody>
    </table>
  </section>

  <section>
    <h2>任务日志</h2>
    <table>
      <thead><tr><th>时间</th><th>任务</th><th>状态</th><th>产物</th><th>输出</th></tr></thead>
      <tbody>{task_rows if task_rows else '<tr><td class="empty" colspan="5">暂无任务日志</td></tr>'}</tbody>
    </table>
  </section>
</main>
</body>
</html>"""


def member_rows_from_form(form: dict[str, list[str]]) -> list[dict[str, str]]:
    ids = form.get("id") or []
    rows = []
    for index, member_id in enumerate(ids):
        rows.append(
            {
                "id": member_id,
                "name": indexed_value(form, "name", index),
                "server_area": indexed_value(form, "server_area", index),
                "qq": indexed_value(form, "qq", index),
                "group_card": indexed_value(form, "group_card", index),
                "active": indexed_value(form, "active", index) or "0",
            }
        )
    return rows


def flow1_settings_from_form(form: dict[str, list[str]]) -> dict[str, str]:
    battle_date = normalize_date_value(form_value(form, "battle_date")) or ""
    return {
        "flow1_raid_day": form_value(form, "raid_day") or "1",
        "flow1_battle_date": battle_date,
        "flow1_pages": form_value(form, "pages") or "12",
        "flow1_scroll_rows": form_value(form, "scroll_rows") or "6",
        "flow1_drag_start_row": form_value(form, "drag_start_row") or "6",
        "flow1_drag_distance_rows": form_value(form, "drag_distance_rows") or "6.1",
        "flow1_drag_end_safe_ratio": form_value(form, "drag_end_safe_ratio") or "0.16",
        "flow1_use_drag_anchor": "1" if form_value(form, "use_drag_anchor") == "1" else "0",
        "flow1_drag_anchor_start": form_value(form, "drag_anchor_start") or "0.53,0.79",
        "flow1_drag_anchor_end": form_value(form, "drag_anchor_end") or "0.53,0.25",
        "flow1_union_point": form_value(form, "union_point") or "0.912,0.395",
        "flow1_raid_entry_point": form_value(form, "raid_entry_point") or "0.50,0.835",
        "flow1_record_point": form_value(form, "record_point"),
        "flow1_day_tab_point": form_value(form, "day_tab_point") or "0.34,0.225",
        "flow1_day1_point": form_value(form, "day1_point") or "0.16,0.278",
        "flow1_day2_point": form_value(form, "day2_point") or "0.31,0.278",
        "flow1_drag_duration_seconds": form_value(form, "drag_duration_seconds") or "1.4",
        "flow1_drag_steps": form_value(form, "drag_steps") or "56",
        "flow1_drag_hold_seconds": form_value(form, "drag_hold_seconds") or "0.35",
        "flow1_skip_open_record": "1" if form_value(form, "skip_open_record") == "1" else "0",
    }


def indexed_value(form: dict[str, list[str]], key: str, index: int) -> str:
    values = form.get(key) or []
    if index >= len(values):
        return ""
    return values[index].strip()


def render_member_row(member: Any) -> str:
    active_selected = "selected" if member.active else ""
    inactive_selected = "" if member.active else "selected"
    return f"""<div class="member-grid">
  <div>#{member.id}</div>
  <input type="hidden" name="id" value="{member.id}">
  <input name="server_area" value="{escape(member.server_area or '')}" placeholder="Q区 / V区">
  <input name="name" value="{escape(member.name)}" required>
  <input name="qq" value="{escape(member.qq or '')}" inputmode="numeric">
  <input name="group_card" value="{escape(member.group_card or '')}">
  <select name="active"><option value="1" {active_selected}>启用</option><option value="0" {inactive_selected}>停用</option></select>
</div>"""


def render_sample_row(row: dict[str, Any]) -> str:
    return (
        f"<tr><td>{escape(str(row.get('name') or ''))}</td>"
        f"<td class=\"num\">{format_number(row.get('power'))}</td>"
        f"<td class=\"num\">{format_number(row.get('level'))}</td>"
        f"<td>{escape(str(row.get('online_text') or row.get('online_status') or ''))}</td></tr>"
    )


def render_day_summary_row(row: dict[str, Any]) -> str:
    member = row["member"]
    damages = list(row.get("damages") or [])[:3]
    while len(damages) < 3:
        damages.append(0)
    return f"""<tr>
  <td>{escape(member.name)}</td>
  <td>{escape(member.server_area or "")}</td>
  <td class="num">{row.get("attack_count") or 0}/3</td>
  <td class="num">{format_number(damages[0])}</td>
  <td class="num">{format_number(damages[1])}</td>
  <td class="num">{format_number(damages[2])}</td>
  <td class="num">{format_number(row.get("total_damage"))}</td>
  <td class="num">{format_number(float(row.get("damage_share") or 0))}</td>
  <td class="num">{row.get("remaining")}</td>
  <td>{escape(str(row.get("notes") or ""))}</td>
</tr>"""


def render_flow1_artifact_row(row: dict[str, str]) -> str:
    path = row.get("path") or ""
    exists = row.get("exists") == "1"
    path_obj = Path(path) if path else None
    if exists and path_obj and path_obj.is_file():
        target = artifact_link(path, "下载")
    elif exists:
        target = f'<span class="path-text">{escape(path)}</span>'
    else:
        target = f'<span class="muted">未生成</span><br><span class="path-text">{escape(path)}</span>'
    status = "可用" if exists else "未生成"
    return f"""<tr>
  <td>{escape(row.get("label") or "")}</td>
  <td>{status}</td>
  <td>{target}</td>
</tr>"""


def render_snapshot_row(snapshot: Any) -> str:
    image = ""
    if snapshot.image_path:
        image = artifact_link(snapshot.image_path, "查看")
        if Path(snapshot.image_path).suffix.lower() in {".png", ".jpg", ".jpeg"}:
            image += f'<br><img class="artifact-img" src="/artifact?path={urllib.parse.quote(snapshot.image_path)}" alt="">'
    return f"""<tr>
  <td>{escape(snapshot.captured_at)}</td>
  <td>{snapshot.raid_day or ""}</td>
  <td>{escape(snapshot.boss_label)}</td>
  <td>{escape(snapshot.boss_name)}</td>
  <td>{snapshot.level or ""}</td>
  <td>{escape(format_hp(snapshot.current_hp, snapshot.total_hp, snapshot.percent))}</td>
  <td>{image}</td>
  <td>{escape(snapshot.note)}</td>
</tr>"""


def render_attack_row(row: dict[str, Any], view_date: str = "") -> str:
    tail = "是" if int(row.get("is_tail") or 0) else ""
    boss = " ".join(str(row.get(key) or "").strip() for key in ("boss_label", "boss_name")).strip()
    view_date_hidden = (
        f'<input type="hidden" name="view_date" value="{escape(view_date)}">'
        if view_date
        else ""
    )
    return f"""<tr>
  <td>{escape(str(row.get("battle_date") or ""))}</td>
  <td>{escape(str(row.get("member_name") or ""))}</td>
  <td>{row.get("attack_no") or ""}</td>
  <td>{escape(boss)}</td>
  <td class="num">{format_number(row.get("damage"))}</td>
  <td>{escape(str(row.get("team_text") or ""))}</td>
  <td>{tail}</td>
  <td>{escape(str(row.get("note") or ""))}</td>
  <td>
    <form method="post" onsubmit="return confirm('删除这条出刀记录？');">
      <input type="hidden" name="action" value="delete_attack">
      <input type="hidden" name="attack_id" value="{row.get("id")}">
      {view_date_hidden}
      <button class="danger" type="submit">删除</button>
    </form>
  </td>
</tr>"""


def render_task_row(task: Any) -> str:
    artifact = artifact_link(task.artifact_path, "打开") if task.artifact_path else ""
    output = task.output[-500:] if task.output else ""
    return f"""<tr>
  <td>{escape(task.started_at)}<br><span class="muted">{escape(task.finished_at)}</span></td>
  <td>{escape(task.title)}<br><span class="muted">{escape(task.command)}</span></td>
  <td class="status-{escape(task.status)}">{escape(task.status)}</td>
  <td>{artifact}</td>
  <td><textarea readonly>{escape(output)}</textarea></td>
</tr>"""


def artifact_link(path: str, label: str) -> str:
    return f'<a href="/artifact?path={urllib.parse.quote(path)}" target="_blank">{escape(label)}</a>'


def form_value(form: dict[str, list[str]], key: str) -> str:
    return (form.get(key) or [""])[0].strip()


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
