from __future__ import annotations

import argparse
import csv
import html
import io
import mimetypes
import re
import sqlite3
import sys
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


DEFAULT_DB = Path("data") / "union_sample.db"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8791

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


@dataclass(frozen=True)
class MemberSample:
    id: int
    name: str
    power: int | None
    level: int | None
    online_text: str
    online_minutes: int | None
    online_status: str
    note: str
    sampled_at: str
    updated_at: str


class UnionSampler:
    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.init_db()

    def close(self) -> None:
        self.conn.close()

    def init_db(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                create table if not exists member_samples (
                    id integer primary key autoincrement,
                    name text not null unique,
                    power integer,
                    level integer,
                    online_text text not null default '',
                    online_minutes integer,
                    online_status text not null default '待确认',
                    note text not null default '',
                    sampled_at text not null,
                    updated_at text not null
                );

                create index if not exists idx_member_samples_power
                    on member_samples(power);
                """
            )
            self.conn.commit()

    def upsert_member(
        self,
        name: str,
        power: int | None = None,
        online_text: str = "",
        level: int | None = None,
        note: str = "",
    ) -> str:
        clean_name = name.strip()
        if not clean_name:
            return "成员名称不能为空。"

        clean_online = online_text.strip()
        online_minutes = parse_online_minutes(clean_online)
        online_status = online_status_from_minutes(online_minutes, clean_online)
        now = now_text()

        with self.lock:
            existing = self.conn.execute(
                "select id from member_samples where name = ?",
                (clean_name,),
            ).fetchone()
            if existing:
                self.conn.execute(
                    """
                    update member_samples
                    set power = coalesce(?, power),
                        level = coalesce(?, level),
                        online_text = ?,
                        online_minutes = ?,
                        online_status = ?,
                        note = ?,
                        updated_at = ?
                    where name = ?
                    """,
                    (
                        power,
                        level,
                        clean_online,
                        online_minutes,
                        online_status,
                        note.strip(),
                        now,
                        clean_name,
                    ),
                )
                self.conn.commit()
                return f"已更新：{clean_name}"

            self.conn.execute(
                """
                insert into member_samples(
                    name, power, level, online_text, online_minutes,
                    online_status, note, sampled_at, updated_at
                )
                values(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_name,
                    power,
                    level,
                    clean_online,
                    online_minutes,
                    online_status,
                    note.strip(),
                    now,
                    now,
                ),
            )
            self.conn.commit()
        return f"已新增：{clean_name}"

    def delete_member(self, member_id: int) -> str:
        with self.lock:
            row = self.conn.execute(
                "select name from member_samples where id = ?",
                (member_id,),
            ).fetchone()
            if not row:
                return f"找不到成员 ID：{member_id}"
            self.conn.execute("delete from member_samples where id = ?", (member_id,))
            self.conn.commit()
        return f"已删除：{row['name']}"

    def list_members(self) -> list[MemberSample]:
        with self.lock:
            rows = self.conn.execute(
                """
                select *
                from member_samples
                order by
                    case when power is null then 1 else 0 end,
                    power desc,
                    id asc
                """
            ).fetchall()
        return [row_to_sample(row) for row in rows]

    def import_text(self, text: str) -> str:
        parsed = parse_batch_text(text)
        if not parsed:
            return "没有解析到成员。格式示例：大魔王 909458 2分钟前 468"

        added = 0
        updated = 0
        skipped = 0
        for item in parsed:
            with self.lock:
                before = self.conn.execute(
                    "select 1 from member_samples where name = ?",
                    (item["name"],),
                ).fetchone()
            msg = self.upsert_member(
                item["name"],
                power=item.get("power"),
                online_text=item.get("online_text", ""),
                level=item.get("level"),
                note=item.get("note", ""),
            )
            if msg.startswith("已新增"):
                added += 1
            elif msg.startswith("已更新") and before:
                updated += 1
            else:
                skipped += 1
        return f"导入完成：新增 {added} 人，更新 {updated} 人，跳过 {skipped} 条。"

    def export_csv(self, delimiter: str = ",") -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=export_headers(), delimiter=delimiter)
        writer.writeheader()
        for member in self.list_members():
            writer.writerow(sample_to_row(member))
        return output.getvalue()


def row_to_sample(row: sqlite3.Row) -> MemberSample:
    return MemberSample(
        id=int(row["id"]),
        name=str(row["name"]),
        power=int(row["power"]) if row["power"] is not None else None,
        level=int(row["level"]) if row["level"] is not None else None,
        online_text=str(row["online_text"] or ""),
        online_minutes=int(row["online_minutes"]) if row["online_minutes"] is not None else None,
        online_status=str(row["online_status"] or "待确认"),
        note=str(row["note"] or ""),
        sampled_at=str(row["sampled_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


def parse_batch_text(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        item = parse_member_line(line)
        if item:
            items.append(item)
    return items


def parse_member_line(line: str) -> dict[str, Any] | None:
    if "," in line or "\t" in line:
        parts = [part.strip() for part in re.split(r"[\t,]+", line) if part.strip()]
        if len(parts) >= 2:
            name = parts[0]
            power = parse_int(parts[1])
            online_text = parts[2] if len(parts) >= 3 else ""
            level = parse_int(parts[3]) if len(parts) >= 4 else None
            note = " ".join(parts[4:]) if len(parts) >= 5 else ""
            return make_item(name, power, online_text, level, note)

    online_match = re.search(r"((?:刚刚|在线|离线)|\d+\s*(?:分钟|小时|天)前)", line)
    online_text = online_match.group(1).replace(" ", "") if online_match else ""
    without_online = line
    if online_match:
        without_online = (line[: online_match.start()] + " " + line[online_match.end() :]).strip()

    nums = list(re.finditer(r"\d+", without_online))
    if not nums:
        return None

    power_match = max(nums, key=lambda m: len(m.group(0)))
    power = parse_int(power_match.group(0))
    left = (without_online[: power_match.start()] + " " + without_online[power_match.end() :]).strip()

    level = None
    level_match = re.search(r"(?:等级|Lv\.?|LV)?\s*(\d{2,3})\b", left, re.IGNORECASE)
    if level_match:
        level = parse_int(level_match.group(1))
        left = (left[: level_match.start()] + " " + left[level_match.end() :]).strip()

    name = re.sub(r"\s+", " ", left).strip(" -|")
    if not name:
        return None
    return make_item(name, power, online_text, level, "")


def make_item(
    name: str,
    power: int | None,
    online_text: str,
    level: int | None,
    note: str,
) -> dict[str, Any] | None:
    clean_name = name.strip()
    if not clean_name:
        return None
    return {
        "name": clean_name,
        "power": power,
        "online_text": online_text.strip(),
        "level": level,
        "note": note.strip(),
    }


def parse_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


def parse_online_minutes(raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    if text in {"刚刚", "在线"}:
        return 0
    if text == "离线":
        return None
    match = re.match(r"(\d+)\s*(分钟|小时|天)前", text)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "分钟":
        return value
    if unit == "小时":
        return value * 60
    if unit == "天":
        return value * 24 * 60
    return None


def online_status_from_minutes(minutes: int | None, raw: str) -> str:
    text = raw.strip()
    if text in {"刚刚", "在线"}:
        return "在线"
    if text == "离线":
        return "离线"
    if minutes is None:
        return "待确认"
    if minutes <= 30:
        return "在线"
    if minutes <= 180:
        return "近期在线"
    return "离线"


def export_headers() -> list[str]:
    return [
        "成员名称",
        "参考战力",
        "游戏等级",
        "在线状态",
        "最近在线",
        "最近在线分钟数",
        "今日已出刀",
        "今日剩余刀",
        "今日总伤害",
        "备注",
        "采样时间",
        "更新时间",
    ]


def sample_to_row(member: MemberSample) -> dict[str, Any]:
    return {
        "成员名称": member.name,
        "参考战力": member.power or "",
        "游戏等级": member.level or "",
        "在线状态": member.online_status,
        "最近在线": member.online_text,
        "最近在线分钟数": member.online_minutes if member.online_minutes is not None else "",
        "今日已出刀": 0,
        "今日剩余刀": 3,
        "今日总伤害": 0,
        "备注": member.note,
        "采样时间": member.sampled_at,
        "更新时间": member.updated_at,
    }


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_handler(sampler: UnionSampler) -> type[BaseHTTPRequestHandler]:
    class SamplerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            notice = (query.get("notice") or [""])[0]
            if path == "/sample-image":
                self.send_local_image((query.get("path") or [""])[0])
                return
            if path == "/members.csv":
                self.send_download(sampler.export_csv(","), "union-members.csv", "text/csv")
                return
            if path == "/members.tsv":
                self.send_download(sampler.export_csv("\t"), "union-members.tsv", "text/tab-separated-values")
                return
            if path != "/":
                self.send_response(404)
                self.end_headers()
                return
            self.send_html(render_page(sampler, notice))

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = urllib.parse.parse_qs(raw)
            action = form_value(form, "action")

            if action == "add":
                notice = sampler.upsert_member(
                    form_value(form, "name"),
                    power=parse_int(form_value(form, "power")),
                    level=parse_int(form_value(form, "level")),
                    online_text=form_value(form, "online_text"),
                    note=form_value(form, "note"),
                )
            elif action == "import":
                notice = sampler.import_text(form_value(form, "batch_text"))
            elif action == "delete":
                notice = sampler.delete_member(int(form_value(form, "id") or "0"))
            else:
                notice = "未知操作。"

            self.redirect(f"/?notice={urllib.parse.quote(notice)}")

        def send_html(self, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_download(self, content: str, filename: str, content_type: str) -> None:
            body = ("\ufeff" + content).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_local_image(self, raw_path: str) -> None:
            if not raw_path:
                self.send_response(404)
                self.end_headers()
                return
            try:
                root = Path.cwd().resolve()
                path = Path(raw_path).resolve()
                path.relative_to(root)
            except Exception:
                self.send_response(403)
                self.end_headers()
                return
            if not path.exists() or not path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            body = path.read_bytes()
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[Sampler] {self.address_string()} - {fmt % args}")

    return SamplerHandler


def form_value(form: dict[str, list[str]], key: str) -> str:
    return (form.get(key) or [""])[0].strip()


def render_page(sampler: UnionSampler, notice: str = "") -> str:
    members = sampler.list_members()
    avatars = latest_avatar_paths(sampler)
    rows = "\n".join(render_member_row(member, avatars.get(member.name, "")) for member in members)
    notice_html = f'<div class="notice">{escape(notice)}</div>' if notice else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NIKKE 联盟队员采样录入</title>
  <style>
    :root {{
      --bg: #f5f6f8;
      --panel: #fff;
      --line: #d8dee8;
      --text: #172033;
      --muted: #657084;
      --primary: #1d63d9;
      --danger: #bb3030;
      --ok: #24733c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Microsoft YaHei", "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 20px;
    }}
    header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }}
    h1 {{ margin: 0 0 4px; font-size: 24px; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    .sub {{ color: var(--muted); }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 14px;
    }}
    .notice {{
      margin-bottom: 14px;
      padding: 10px 12px;
      border: 1px solid #afd7bb;
      border-radius: 6px;
      background: #eef9f1;
      color: var(--ok);
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 150px 120px 140px 1fr auto;
      gap: 10px;
      align-items: end;
    }}
    label {{ display: grid; gap: 5px; color: var(--muted); font-size: 12px; }}
    input, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 9px;
      color: var(--text);
      background: #fff;
      font: inherit;
    }}
    textarea {{
      min-height: 130px;
      resize: vertical;
      font-family: Consolas, "Microsoft YaHei", monospace;
    }}
    button, .button {{
      min-height: 36px;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 8px 12px;
      background: var(--primary);
      color: #fff;
      font: inherit;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }}
    .button.secondary, button.secondary {{
      background: #fff;
      color: var(--primary);
      border-color: var(--primary);
    }}
    button.danger {{
      background: #fff;
      color: var(--danger);
      border-color: #e0b2b2;
    }}
    .tools {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }}
    .hint {{
      color: var(--muted);
      margin: 0 0 10px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      text-align: left;
      vertical-align: middle;
      overflow-wrap: anywhere;
    }}
    th {{
      color: var(--muted);
      background: #fafbfc;
      font-size: 12px;
      font-weight: 600;
    }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .avatar {{
      width: 48px;
      height: 48px;
      object-fit: cover;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: #f3f4f6;
    }}
    .avatar-empty {{
      width: 48px;
      height: 48px;
      border-radius: 6px;
      border: 1px dashed var(--line);
      background: #f3f4f6;
    }}
    .empty {{ padding: 28px; text-align: center; color: var(--muted); }}
    @media (max-width: 860px) {{
      main {{ padding: 12px; }}
      header {{ display: block; }}
      .grid {{ grid-template-columns: 1fr; }}
      .tools {{ justify-content: flex-start; margin-top: 10px; }}
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
      <h1>NIKKE 联盟队员采样录入</h1>
      <div class="sub">当前已录入 {len(members)} 人，数据文件：{escape(str(sampler.db_path))}</div>
    </div>
    <div class="tools">
      <a class="button secondary" href="/members.tsv">导出 TSV</a>
      <a class="button secondary" href="/members.csv">导出 CSV</a>
    </div>
  </header>
  {notice_html}

  <section>
    <h2>单个录入</h2>
    <form class="grid" method="post">
      <input type="hidden" name="action" value="add">
      <label>成员名称<input name="name" required placeholder="大魔王"></label>
      <label>参考战力<input name="power" inputmode="numeric" placeholder="909458"></label>
      <label>游戏等级<input name="level" inputmode="numeric" placeholder="468"></label>
      <label>最近在线<input name="online_text" placeholder="2分钟前"></label>
      <label>备注<input name="note" placeholder="请假 / 待确认 / 只打尾刀"></label>
      <button type="submit">保存</button>
    </form>
  </section>

  <section>
    <h2>批量粘贴</h2>
    <p class="hint">每行一个成员。支持空格、逗号或 Tab：成员名 参考战力 最近在线 等级。示例：大魔王 909458 2分钟前 468</p>
    <form method="post">
      <input type="hidden" name="action" value="import">
      <textarea name="batch_text" required placeholder="大魔王 909458 2分钟前 468&#10;DORO 931291 3分钟前 484"></textarea>
      <button type="submit" style="margin-top:10px;">批量导入 / 更新</button>
    </form>
  </section>

  <section>
    <table>
      <thead>
        <tr>
          <th style="width:58px;">ID</th>
          <th style="width:70px;">头像</th>
          <th>成员名称</th>
          <th class="num">参考战力</th>
          <th class="num">等级</th>
          <th>在线状态</th>
          <th>最近在线</th>
          <th>备注</th>
          <th style="width:88px;">操作</th>
        </tr>
      </thead>
      <tbody>
        {rows if rows else '<tr><td class="empty" colspan="9">还没有录入成员</td></tr>'}
      </tbody>
    </table>
  </section>
</main>
</body>
</html>"""


def latest_avatar_paths(sampler: UnionSampler) -> dict[str, str]:
    try:
        with sampler.lock:
            rows = sampler.conn.execute(
                """
                select member_name, avatar_image_path
                from member_avatar_samples
                where id in (
                    select max(id)
                    from member_avatar_samples
                    group by member_name
                )
                """
            ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(row["member_name"]): str(row["avatar_image_path"]) for row in rows}


def render_member_row(member: MemberSample, avatar_path: str = "") -> str:
    avatar_html = (
        f'<img class="avatar" src="/sample-image?path={urllib.parse.quote(avatar_path)}" alt="">'
        if avatar_path
        else '<div class="avatar-empty"></div>'
    )
    return f"""<tr>
  <td>#{member.id}</td>
  <td>{avatar_html}</td>
  <td>{escape(member.name)}</td>
  <td class="num">{member.power or ""}</td>
  <td class="num">{member.level or ""}</td>
  <td>{escape(member.online_status)}</td>
  <td>{escape(member.online_text)}</td>
  <td>{escape(member.note)}</td>
  <td>
    <form method="post" onsubmit="return confirm('确定删除这个成员采样？');">
      <input type="hidden" name="action" value="delete">
      <input type="hidden" name="id" value="{member.id}">
      <button class="danger" type="submit">删除</button>
    </form>
  </td>
</tr>"""


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def run_web(args: argparse.Namespace) -> int:
    sampler = UnionSampler(args.db)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(sampler))
    print(f"联盟队员采样录入页面：http://{args.host}:{args.port}/")
    print(f"数据文件：{sampler.db_path}")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        sampler.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NIKKE 联盟队员采样录入工具")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据文件")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="初始化数据库")

    add = sub.add_parser("add", help="录入或更新单个成员")
    add.add_argument("name")
    add.add_argument("--power")
    add.add_argument("--level")
    add.add_argument("--online", default="")
    add.add_argument("--note", default="")

    imp = sub.add_parser("import-text", help="从文本文件批量导入")
    imp.add_argument("path")

    exp = sub.add_parser("export", help="导出 CSV/TSV")
    exp.add_argument("--format", choices=["csv", "tsv"], default="tsv")
    exp.add_argument("--output")

    web = sub.add_parser("web", help="启动本地录入页面")
    web.add_argument("--host", default=DEFAULT_HOST)
    web.add_argument("--port", type=int, default=DEFAULT_PORT)

    args = parser.parse_args(argv)
    if args.command == "web":
        return run_web(args)

    sampler = UnionSampler(args.db)
    try:
        if args.command == "init":
            print(f"数据库已初始化：{sampler.db_path}")
            return 0
        if args.command == "add":
            print(
                sampler.upsert_member(
                    args.name,
                    power=parse_int(args.power),
                    level=parse_int(args.level),
                    online_text=args.online,
                    note=args.note,
                )
            )
            return 0
        if args.command == "import-text":
            text = Path(args.path).read_text(encoding="utf-8-sig")
            print(sampler.import_text(text))
            return 0
        if args.command == "export":
            delimiter = "\t" if args.format == "tsv" else ","
            data = sampler.export_csv(delimiter)
            if args.output:
                Path(args.output).write_text("\ufeff" + data, encoding="utf-8")
                print(f"已导出：{args.output}")
            else:
                print(data, end="")
            return 0
    finally:
        sampler.close()

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
