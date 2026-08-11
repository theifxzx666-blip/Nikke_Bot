from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path


DEFAULT_DB_PATH = Path("data") / "guild_war.db"
MAX_ATTACKS_PER_MEMBER = 3
NO_ATTACK_COMMAND = object()
RAID_START = datetime(2026, 6, 12, 4, 0)
RAID_END = datetime(2026, 6, 18, 3, 59)
RAID_SETTLEMENT_END = datetime(2026, 6, 20, 23, 59)
RAID_DAY_START_HOUR = 4
MAIN_RAID_DAYS = 2


@dataclass(frozen=True)
class MemberStatus:
    id: int
    name: str
    qq: str | None
    attacks: int
    total_damage: int

    @property
    def remaining(self) -> int:
        return max(0, MAX_ATTACKS_PER_MEMBER - self.attacks)

    @property
    def done(self) -> bool:
        return self.attacks >= MAX_ATTACKS_PER_MEMBER


@dataclass(frozen=True)
class MemberRecord:
    id: int
    name: str
    server_area: str | None
    qq: str | None
    group_card: str | None
    active: bool


def db_path_from_env() -> Path:
    return Path(os.environ.get("GUILD_WAR_DB", DEFAULT_DB_PATH))


class GuildWarBot:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else db_path_from_env()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.init_db()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def init_db(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                create table if not exists members (
                    id integer primary key autoincrement,
                    name text not null unique,
                    server_area text,
                    qq text,
                    group_card text,
                    active integer not null default 1,
                    created_at text not null default current_timestamp
                );

                create table if not exists attacks (
                    id integer primary key autoincrement,
                    member_id integer not null,
                    battle_date text not null,
                    damage integer,
                    note text,
                    created_at text not null default current_timestamp,
                    foreign key(member_id) references members(id)
                );

                create index if not exists idx_attacks_member_date
                    on attacks(member_id, battle_date);
                """
            )
            self.ensure_column("members", "server_area", "text")
            self.ensure_column("members", "group_card", "text")
            self.conn.commit()

    def ensure_column(self, table: str, column: str, column_type: str) -> None:
        columns = {
            str(row["name"])
            for row in self.conn.execute(f"pragma table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"alter table {table} add column {column} {column_type}")

    def add_member(
        self,
        name: str,
        qq: str | None = None,
        group_card: str | None = None,
        server_area: str | None = None,
    ) -> str:
        clean_name = name.strip()
        if not clean_name:
            return "成员名不能为空。"
        with self.lock:
            try:
                self.conn.execute(
                    "insert into members(name, server_area, qq, group_card) values(?, ?, ?, ?)",
                    (
                        clean_name,
                        normalize_server_area(server_area),
                        qq.strip() if qq else None,
                        group_card.strip() if group_card else None,
                    ),
                )
                self.conn.commit()
                return f"已添加成员：{clean_name}"
            except sqlite3.IntegrityError:
                return f"成员已存在：{clean_name}"

    def import_members(self, csv_path: Path | str) -> str:
        path = Path(csv_path)
        added = 0
        skipped = 0
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                name = (row.get("name") or "").strip()
                server_area = (row.get("server_area") or row.get("区服") or "").strip() or None
                qq = (row.get("qq") or "").strip() or None
                group_card = (row.get("group_card") or row.get("Q群备注名") or "").strip() or None
                if not name:
                    skipped += 1
                    continue
                before = self.member_count()
                self.add_member(name, qq, group_card, server_area)
                if self.member_count() > before:
                    added += 1
                else:
                    skipped += 1
        return f"导入完成：新增 {added} 人，跳过 {skipped} 条。"

    def export_members_csv(self) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["id", "name", "server_area", "qq", "group_card", "active"],
        )
        writer.writeheader()
        for record in self.list_member_records(include_inactive=True):
            writer.writerow(
                {
                    "id": record.id,
                    "name": record.name,
                    "server_area": record.server_area or "",
                    "qq": record.qq or "",
                    "group_card": record.group_card or "",
                    "active": "1" if record.active else "0",
                }
            )
        return output.getvalue()

    def import_members_csv_text(self, csv_text: str) -> str:
        added = 0
        updated = 0
        skipped = 0
        reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
        if not reader.fieldnames:
            return "导入失败：CSV 内容为空。"

        for row in reader:
            name = (row.get("name") or row.get("成员名") or "").strip()
            server_area = (
                row.get("server_area")
                or row.get("区服")
                or row.get("server")
                or row.get("area")
                or ""
            ).strip()
            qq = (
                row.get("qq")
                or row.get("QQ")
                or row.get("QQ号")
                or row.get("Q群QQ号")
                or ""
            ).strip()
            group_card = (
                row.get("group_card")
                or row.get("Q群备注名")
                or row.get("群备注")
                or row.get("群名片")
                or ""
            ).strip()
            active = parse_active(row.get("active") or row.get("启用") or "1")
            raw_id = (row.get("id") or row.get("ID") or "").strip()
            if not name:
                skipped += 1
                continue

            member_id = int(raw_id) if raw_id.isdigit() else None
            if member_id and self.member_id_exists(member_id):
                notice = self.update_member(
                    member_id,
                    name,
                    qq or None,
                    active,
                    group_card or None,
                    server_area or None,
                )
                if notice.startswith("已更新"):
                    updated += 1
                else:
                    skipped += 1
                continue

            existing = self.find_member_record_by_name(name)
            if existing:
                notice = self.update_member(
                    existing.id,
                    name,
                    qq or None,
                    active,
                    group_card or None,
                    server_area or None,
                )
                if notice.startswith("已更新"):
                    updated += 1
                else:
                    skipped += 1
                continue

            before = self.member_count(include_inactive=True)
            self.add_member(name, qq or None, group_card or None, server_area or None)
            existing = self.find_member_record_by_name(name)
            if existing and not active:
                self.update_member(
                    existing.id,
                    name,
                    qq or None,
                    active,
                    group_card or None,
                    server_area or None,
                )
            if self.member_count(include_inactive=True) > before:
                added += 1
            else:
                skipped += 1

        return f"导入完成：新增 {added} 人，更新 {updated} 人，跳过 {skipped} 条。"

    def member_count(self, include_inactive: bool = False) -> int:
        where = "" if include_inactive else "where active = 1"
        with self.lock:
            row = self.conn.execute(
                f"select count(*) as c from members {where}"
            ).fetchone()
        return int(row["c"])

    def find_member(self, name: str) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(
                "select * from members where active = 1 and name = ?",
                (name.strip(),),
            ).fetchone()

    def find_member_by_qq(self, qq: str | None) -> sqlite3.Row | None:
        clean_qq = (qq or "").strip()
        if not clean_qq:
            return None
        with self.lock:
            return self.conn.execute(
                "select * from members where active = 1 and qq = ?",
                (clean_qq,),
            ).fetchone()

    def resolve_member_name(self, sender_name: str, sender_qq: str | None = None) -> str:
        member = self.find_member_by_qq(sender_qq)
        if member:
            return str(member["name"])
        return sender_name

    def list_members(self) -> list[str]:
        with self.lock:
            rows = self.conn.execute(
                "select name from members where active = 1 order by id"
            ).fetchall()
        return [row["name"] for row in rows]

    def list_member_records(self, include_inactive: bool = True) -> list[MemberRecord]:
        where = "" if include_inactive else "where active = 1"
        with self.lock:
            rows = self.conn.execute(
                f"select id, name, server_area, qq, group_card, active from members {where} order by active desc, server_area, id"
            ).fetchall()
        return [
            MemberRecord(
                id=int(row["id"]),
                name=str(row["name"]),
                server_area=row["server_area"],
                qq=row["qq"],
                group_card=row["group_card"],
                active=bool(row["active"]),
            )
            for row in rows
        ]

    def member_id_exists(self, member_id: int) -> bool:
        with self.lock:
            row = self.conn.execute(
                "select 1 from members where id = ?",
                (member_id,),
            ).fetchone()
        return row is not None

    def find_member_record_by_name(self, name: str) -> MemberRecord | None:
        with self.lock:
            row = self.conn.execute(
                "select id, name, server_area, qq, group_card, active from members where name = ?",
                (name.strip(),),
            ).fetchone()
        if not row:
            return None
        return MemberRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            server_area=row["server_area"],
            qq=row["qq"],
            group_card=row["group_card"],
            active=bool(row["active"]),
        )

    def update_member(
        self,
        member_id: int,
        name: str,
        qq: str | None = None,
        active: bool = True,
        group_card: str | None = None,
        server_area: str | None = None,
    ) -> str:
        clean_name = name.strip()
        clean_server_area = normalize_server_area(server_area)
        clean_qq = (qq or "").strip() or None
        clean_group_card = (group_card or "").strip() or None
        if not clean_name:
            return "成员名不能为空。"
        with self.lock:
            try:
                cur = self.conn.execute(
                    """
                    update members
                    set name = ?, server_area = ?, qq = ?, group_card = ?, active = ?
                    where id = ?
                    """,
                    (
                        clean_name,
                        clean_server_area,
                        clean_qq,
                        clean_group_card,
                        1 if active else 0,
                        member_id,
                    ),
                )
                self.conn.commit()
            except sqlite3.IntegrityError:
                return f"成员名已存在：{clean_name}"
        if cur.rowcount == 0:
            return f"找不到成员 ID：{member_id}"
        return f"已更新成员：{clean_name}"

    def bulk_update_members(self, rows: list[dict[str, str]]) -> str:
        updated = 0
        skipped = 0
        for row in rows:
            raw_id = str(row.get("id") or "").strip()
            if not raw_id.isdigit():
                skipped += 1
                continue
            notice = self.update_member(
                int(raw_id),
                str(row.get("name") or ""),
                str(row.get("qq") or "") or None,
                parse_active(row.get("active") or "1"),
                str(row.get("group_card") or "") or None,
                str(row.get("server_area") or "") or None,
            )
            if notice.startswith("已更新"):
                updated += 1
            else:
                skipped += 1
        return f"批量保存完成：更新 {updated} 人，跳过 {skipped} 条。"

    def delete_member(self, member_id: int) -> str:
        with self.lock:
            row = self.conn.execute(
                "select name from members where id = ?",
                (member_id,),
            ).fetchone()
            if not row:
                return f"找不到成员 ID：{member_id}"
            self.conn.execute("delete from attacks where member_id = ?", (member_id,))
            self.conn.execute("delete from members where id = ?", (member_id,))
            self.conn.commit()
        return f"已删除成员：{row['name']}"

    def record_attack(
        self,
        member_name: str,
        damage: int | None = None,
        note: str | None = None,
        battle_date: date | None = None,
    ) -> str:
        with self.lock:
            member = self.find_member(member_name)
            if not member:
                return f"找不到成员：{member_name}。请先添加成员。"

            day = (battle_date or battle_day()).isoformat()
            attacks = self.attack_count(member["id"], day)
            if attacks >= MAX_ATTACKS_PER_MEMBER:
                return f"{member_name} 今天已经出满 {MAX_ATTACKS_PER_MEMBER} 刀了。"

            self.conn.execute(
                """
                insert into attacks(member_id, battle_date, damage, note)
                values(?, ?, ?, ?)
                """,
                (member["id"], day, damage, note),
            )
            self.conn.commit()

        new_count = attacks + 1
        damage_text = f"，伤害 {format_damage(damage)}" if damage else ""
        return f"已记录：{member_name} 第 {new_count}/{MAX_ATTACKS_PER_MEMBER} 刀{damage_text}。"

    def update_attack_damage(
        self,
        member_name: str,
        damage: int,
        attack_index: int | None = None,
        battle_date: date | None = None,
    ) -> str:
        name = member_name.strip()
        if not name:
            return "格式：改伤害 成员名 1200w [第几刀]"
        if damage <= 0:
            return "伤害格式不正确，例如：1200w、3500万、12500000。"

        day = (battle_date or battle_day()).isoformat()
        with self.lock:
            member = self.find_member(name)
            if not member:
                return f"找不到成员：{name}。请先添加成员。"

            rows = self.conn.execute(
                """
                select id, damage
                from attacks
                where member_id = ? and battle_date = ?
                order by id
                """,
                (member["id"], day),
            ).fetchall()
            if not rows:
                return f"{name} 今天还没有出刀记录，不能修改伤害。"

            target_index = attack_index if attack_index is not None else len(rows)
            if target_index < 1 or target_index > len(rows):
                return f"{name} 今天只有 {len(rows)} 刀记录，找不到第 {target_index} 刀。"

            target = rows[target_index - 1]
            self.conn.execute(
                "update attacks set damage = ?, note = ? where id = ?",
                (damage, format_damage(damage), target["id"]),
            )
            self.conn.commit()

        return f"已更新：{name} 第 {target_index} 刀伤害为 {format_damage(damage)}。"

    def damage_ranking(self, battle_date: date | None = None) -> str:
        day = battle_date or battle_day()
        rows = self.damage_table_rows(day)
        if not rows:
            return "成员名单为空，请先导入成员。"

        ranked = sorted(rows, key=lambda row: row["total_damage"], reverse=True)
        total_damage = sum(row["total_damage"] for row in ranked)
        average_damage = total_damage // len(ranked) if ranked else 0
        lines = [
            f"{day.isoformat()} 联盟突袭伤害统计：",
            f"总伤害：{format_damage(total_damage)}",
            f"均伤：{format_damage(average_damage)}",
            "排名｜成员｜第一刀｜第二刀｜第三刀｜总伤｜占比｜备注",
        ]
        for index, row in enumerate(ranked, start=1):
            ratio = row["total_damage"] / total_damage if total_damage else 0
            attacks = row["attacks"]
            attack_text = "｜".join(format_damage(value) for value in attacks)
            note_text = row["note"] or "-"
            lines.append(
                f"{index}｜{row['name']}｜{attack_text}｜{format_damage(row['total_damage'])}｜{ratio:.1%}｜{note_text}"
            )
        return "\n".join(lines)

    def damage_table_rows(self, battle_date: date | None = None) -> list[dict[str, object]]:
        day = (battle_date or battle_day()).isoformat()
        with self.lock:
            members = self.conn.execute(
                "select id, name from members where active = 1 order by id"
            ).fetchall()
            attacks = self.conn.execute(
                """
                select member_id, damage, note
                from attacks
                where battle_date = ?
                order by member_id, id
                """,
                (day,),
            ).fetchall()

        by_member: dict[int, list[sqlite3.Row]] = {}
        for attack in attacks:
            by_member.setdefault(int(attack["member_id"]), []).append(attack)

        rows: list[dict[str, object]] = []
        for member in members:
            member_attacks = by_member.get(int(member["id"]), [])
            damage_values = [
                int(attack["damage"] or 0)
                for attack in member_attacks[:MAX_ATTACKS_PER_MEMBER]
            ]
            while len(damage_values) < MAX_ATTACKS_PER_MEMBER:
                damage_values.append(0)
            notes = [
                str(attack["note"] or "").strip()
                for attack in member_attacks
                if str(attack["note"] or "").strip()
                and str(attack["note"] or "").strip() != format_damage(attack["damage"])
            ]
            rows.append(
                {
                    "name": str(member["name"]),
                    "attacks": damage_values,
                    "total_damage": sum(damage_values),
                    "note": "；".join(notes),
                }
            )
        return rows

    def damage_summary(self, battle_date: date | None = None) -> str:
        day = battle_date or battle_day()
        statuses = self.statuses(day)
        if not statuses:
            return "成员名单为空，请先导入成员。"

        total_damage = sum(status.total_damage for status in statuses)
        total_attacks = sum(status.attacks for status in statuses)
        recorded_damage_attacks = sum(1 for status in statuses if status.total_damage > 0)
        average_damage = total_damage // total_attacks if total_attacks else 0
        top = max(statuses, key=lambda status: status.total_damage)
        return "\n".join(
            [
                f"{day.isoformat()} 伤害概览：",
                f"总伤害：{format_damage(total_damage)}",
                f"已出刀：{total_attacks}/{len(statuses) * MAX_ATTACKS_PER_MEMBER}",
                f"人均已记录伤害：{format_damage(average_damage)} / 刀",
                f"有伤害记录成员：{recorded_damage_attacks}/{len(statuses)} 人",
                f"当前最高：{top.name} {format_damage(top.total_damage)}",
            ]
        )

    def attack_count(self, member_id: int, battle_date: str) -> int:
        with self.lock:
            row = self.conn.execute(
                """
                select count(*) as c
                from attacks
                where member_id = ? and battle_date = ?
                """,
                (member_id, battle_date),
            ).fetchone()
        return int(row["c"])

    def statuses(self, battle_date: date | None = None) -> list[MemberStatus]:
        day = (battle_date or battle_day()).isoformat()
        with self.lock:
            rows = self.conn.execute(
                """
                select
                    m.id,
                    m.name,
                    m.qq,
                    count(a.id) as attacks,
                    coalesce(sum(a.damage), 0) as total_damage
                from members m
                left join attacks a
                    on a.member_id = m.id
                    and a.battle_date = ?
                where m.active = 1
                group by m.id, m.name, m.qq
                order by m.id
                """,
                (day,),
            ).fetchall()
        return [
            MemberStatus(
                id=row["id"],
                name=row["name"],
                qq=row["qq"],
                attacks=int(row["attacks"]),
                total_damage=int(row["total_damage"] or 0),
            )
            for row in rows
        ]

    def summary(self, battle_date: date | None = None) -> str:
        day = battle_date or battle_day()
        statuses = self.statuses(day)
        total_members = len(statuses)
        total_required = total_members * MAX_ATTACKS_PER_MEMBER
        total_attacks = sum(status.attacks for status in statuses)
        unfinished = [status for status in statuses if not status.done]

        lines = [
            f"{day.isoformat()} 公会战进度：{total_attacks}/{total_required} 刀",
            f"已出满：{total_members - len(unfinished)}/{total_members} 人",
        ]
        if not statuses:
            lines.append("成员名单为空，请先导入成员。")
            return "\n".join(lines)

        if unfinished:
            lines.append("")
            lines.append("未出满：")
            for status in unfinished:
                lines.append(
                    f"- {status.name} {status.attacks}/{MAX_ATTACKS_PER_MEMBER}"
                )
        else:
            lines.append("")
            lines.append("全员已出满。")
        return "\n".join(lines)

    def member_report(
        self,
        member_name: str,
        battle_date: date | None = None,
    ) -> str:
        day = battle_date or battle_day()
        name = member_name.strip()
        if not name:
            return "格式：查刀 成员名，例如：查刀 张三"

        with self.lock:
            member = self.find_member(name)
            if not member:
                return f"找不到成员：{name}。请先在成员管理后台添加或确认名称。"

            rows = self.conn.execute(
                """
                select damage, note, created_at
                from attacks
                where member_id = ? and battle_date = ?
                order by id
                """,
                (member["id"], day.isoformat()),
            ).fetchall()

        attacks = len(rows)
        total_damage = sum(int(row["damage"] or 0) for row in rows)
        remaining = max(0, MAX_ATTACKS_PER_MEMBER - attacks)
        lines = [
            f"{day.isoformat()} {name} 出刀情况：{attacks}/{MAX_ATTACKS_PER_MEMBER}",
            f"剩余：{remaining} 刀",
            f"总伤害：{format_damage(total_damage)}",
        ]

        if not rows:
            lines.append("今日还没有出刀记录。")
            return "\n".join(lines)

        lines.append("明细：")
        for index, row in enumerate(rows, start=1):
            damage = format_damage(row["damage"])
            note = str(row["note"] or "").strip()
            note_text = f"，备注 {note}" if note and note != damage else ""
            created_at = str(row["created_at"] or "")
            time_text = created_at[11:16] if len(created_at) >= 16 else created_at
            lines.append(f"- 第 {index} 刀：{damage}{note_text}，{time_text}")
        return "\n".join(lines)

    def remind_text(self, battle_date: date | None = None) -> str:
        statuses = self.statuses(battle_date)
        unfinished = [status for status in statuses if not status.done]
        if not statuses:
            return "成员名单为空，请先导入成员。"
        if not unfinished:
            return "全员已出满，今天很稳。"

        lines = ["请以下成员尽快出刀："]
        for status in unfinished:
            mention = f"@{self.display_name_for_member(status.id, status.name)}"
            lines.append(
                f"{mention} 还剩 {status.remaining} 刀（当前 {status.attacks}/{MAX_ATTACKS_PER_MEMBER}）"
            )
        return "\n".join(lines)

    def urge_zero_attack_text(self, battle_date: date | None = None) -> str:
        if battle_date is None and not is_main_raid_day():
            return (
                raid_status_text()
                + "\n\n当前不在重点催刀期。若仍需提醒，请使用 /提醒未出刀 查看未出满成员。"
            )
        statuses = self.statuses(battle_date)
        zero_attack = [status for status in statuses if status.attacks == 0]
        if not statuses:
            return "成员名单为空，请先导入成员。"
        if not zero_attack:
            return "今天没有 0 刀成员，大家都已经开刀了。"

        lines = ["请以下 0 刀成员尽快出刀："]
        for status in zero_attack:
            mention = f"@{self.display_name_for_member(status.id, status.name)}"
            lines.append(f"{mention} 当前 0/{MAX_ATTACKS_PER_MEMBER} 刀")
        return "\n".join(lines)

    def display_name_for_member(self, member_id: int, fallback: str) -> str:
        with self.lock:
            row = self.conn.execute(
                "select group_card from members where id = ?",
                (member_id,),
            ).fetchone()
        if row and str(row["group_card"] or "").strip():
            return str(row["group_card"]).strip()
        return fallback

    def daily_report(self, battle_date: date | None = None) -> str:
        day = battle_date or battle_day()
        statuses = self.statuses(day)
        total_damage = sum(status.total_damage for status in statuses)
        lines = [
            self.summary(day),
            "",
            f"总伤害：{format_damage(total_damage)}",
            "",
            "成员明细：",
        ]
        for status in statuses:
            lines.append(
                f"- {status.name} {status.attacks}/{MAX_ATTACKS_PER_MEMBER}，伤害 {format_damage(status.total_damage)}"
            )
        return "\n".join(lines)

    def reset_day(self, battle_date: date | None = None) -> str:
        day = (battle_date or battle_day()).isoformat()
        with self.lock:
            row = self.conn.execute(
                "select count(*) as c from attacks where battle_date = ?",
                (day,),
            ).fetchone()
            count = int(row["c"])
            self.conn.execute("delete from attacks where battle_date = ?", (day,))
            self.conn.commit()
        return f"已清空 {day} 的 {count} 条出刀记录。"

    def handle_message(
        self,
        sender_name: str,
        text: str,
        is_admin: bool = False,
        sender_qq: str | None = None,
    ) -> str | None:
        content = normalize_command(text)
        if not content:
            return None

        if content in {"帮助", "菜单", "指令", "help"}:
            return help_text()

        for prefix in ("查刀 ", "查询 ", "查成员 "):
            if content.startswith(prefix):
                return self.member_report(content[len(prefix) :])

        if content in {"查刀", "进度", "统计", "/查刀"}:
            return self.summary()

        if content in {"未出刀", "提醒未出刀", "提醒", "/提醒"}:
            return self.remind_text()

        if content in {"催刀", "催一下", "催0刀"}:
            return self.urge_zero_attack_text()

        if content in {"会战时间", "突袭时间", "活动时间"}:
            return raid_status_text()

        if content in {"日报", "结算", "/日报"}:
            return self.daily_report()

        if content in {"伤害", "伤害统计", "伤害榜", "排行"}:
            return self.damage_ranking()

        if content in {"伤害概览", "伤害汇总"}:
            return self.damage_summary()

        if content in {"成员", "名单", "/成员"}:
            members = self.list_members()
            if not members:
                return "成员名单为空。"
            return "成员名单：\n" + "\n".join(f"- {name}" for name in members)

        if content in {"重置今日", "清空今日", "/重置"}:
            if not is_admin:
                return "只有管理员可以重置今日记录。"
            return self.reset_day()

        attack = parse_attack_command(content)
        if attack is not NO_ATTACK_COMMAND:
            damage, note = attack
            member_name = self.resolve_member_name(sender_name, sender_qq)
            return self.record_attack(member_name, damage=damage, note=note)

        if is_admin and content.startswith("代出刀 "):
            parts = content.split(maxsplit=2)
            if len(parts) < 2:
                return "格式：代出刀 成员名 [伤害]"
            target = parts[1]
            damage = parse_damage(parts[2]) if len(parts) > 2 else None
            return self.record_attack(target, damage=damage)

        if is_admin and content.startswith("改伤害 "):
            parts = content.split()
            if len(parts) < 3:
                return "格式：改伤害 成员名 1200w [第几刀]"
            target = parts[1]
            damage = parse_damage(parts[2])
            if damage is None:
                return "伤害格式不正确，例如：1200w、3500万、12500000。"
            attack_index = parse_attack_index(parts[3]) if len(parts) > 3 else None
            if len(parts) > 3 and attack_index is None:
                return "第几刀格式不正确，例如：1、2、3、第2刀。"
            return self.update_attack_damage(target, damage, attack_index)

        return None


def normalize_command(text: str) -> str:
    content = text.strip()
    content = re.sub(r"^@\S+\s*", "", content)
    content = content.lstrip("/／")
    return content.strip()


def battle_day(now: datetime | None = None) -> date:
    current = now or datetime.now()
    if current.time() < time(RAID_DAY_START_HOUR, 0):
        return (current - timedelta(days=1)).date()
    return current.date()


def raid_day_number(now: datetime | None = None) -> int | None:
    current = now or datetime.now()
    if current < RAID_START or current > RAID_END:
        return None
    current_day = battle_day(current)
    first_day = RAID_START.date()
    if current_day < first_day:
        return None
    return (current_day - first_day).days + 1


def is_main_raid_day(now: datetime | None = None) -> bool:
    day_number = raid_day_number(now)
    return day_number is not None and 1 <= day_number <= MAIN_RAID_DAYS


def raid_status_text(now: datetime | None = None) -> str:
    current = now or datetime.now()
    current_battle_day = battle_day(current)
    day_number = raid_day_number(current)
    lines = [
        "联盟突袭时间：",
        "开启：2026-06-12 04:00",
        "结束：2026-06-18 03:59",
        "结算：2026-06-18 04:00 ~ 2026-06-20 23:59",
        f"当前战斗日：{current_battle_day.isoformat()}（每日 04:00 切日）",
    ]
    if day_number:
        lines.append(f"当前第 {day_number} 天。")
        if day_number <= MAIN_RAID_DAYS:
            lines.append("当前属于重点催刀期：前 2 天。")
        else:
            lines.append("当前已过重点催刀期，建议按需手动提醒。")
    elif current < RAID_START:
        lines.append("联盟突袭尚未开启。")
    elif current <= RAID_SETTLEMENT_END:
        lines.append("联盟突袭已结束，当前处于结算期。")
    else:
        lines.append("本期联盟突袭已结束。")
    return "\n".join(lines)


def parse_attack_command(content: str) -> tuple[int | None, str | None] | object:
    if content == "出刀":
        return None, None
    match = re.match(r"^出刀\s+(.+)$", content)
    if not match:
        return NO_ATTACK_COMMAND
    raw = match.group(1).strip()
    damage = parse_damage(raw)
    return damage, raw


def parse_damage(raw: str) -> int | None:
    text = raw.strip().lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*([w万k千]?)", text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit in {"w", "万"}:
        value *= 10_000
    elif unit in {"k", "千"}:
        value *= 1_000
    return int(value)


def parse_attack_index(raw: str) -> int | None:
    match = re.search(r"([1-9]\d*)", raw)
    if not match:
        return None
    return int(match.group(1))


def parse_active(raw: str | None) -> bool:
    text = (raw or "").strip().lower()
    if text in {"0", "false", "no", "n", "否", "停用", "禁用"}:
        return False
    return True


def normalize_server_area(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    upper = text.upper()
    if "Q" in upper or "Ｑ" in text or "Q区" in text:
        return "Q区"
    if "V" in upper or "Ｖ" in text or "V区" in text:
        return "V区"
    return text


def format_damage(value: int | None) -> str:
    if not value:
        return "0"
    if value >= 10_000:
        number = f"{value / 10_000:.1f}".rstrip("0").rstrip(".")
        return f"{number}万"
    return str(value)


def help_text() -> str:
    return (
        "公会战机器人指令：\n"
        "QQ群用法：@机器人 /指令，例如 @机器人 /帮助\n"
        "\n"
        "成员可用：\n"
        "- /帮助：查看这份菜单\n"
        "- /查刀：查看今日总进度和未出满成员\n"
        "- /查刀 成员名：查看某个成员今日出刀情况\n"
        "- /伤害榜：查看今日伤害排行\n"
        "- /伤害概览：查看总伤害、均伤和最高伤害\n"
        "- /会战进度查询：自动进入游戏并发送会战进度截图\n"
        "- /会战时间：查看联盟突袭时间和当前战斗日\n"
        "- /出刀：记录自己出刀 1 次\n"
        "- /出刀 1200w：记录自己出刀并附带伤害\n"
        "- /成员：查看成员名单\n"
        "\n"
        "管理员可用：\n"
        "- /催刀：提醒今日 0 刀成员\n"
        "- /提醒未出刀：生成未出满提醒\n"
        "- /日报：查看今日出刀和伤害日报\n"
        "- /重置今日：清空今日出刀记录\n"
        "- /代出刀 成员名 1200w：帮成员补记出刀\n"
        "- /改伤害 成员名 1200w [第几刀]：修改成员今日伤害"
    )


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
