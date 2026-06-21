#!/usr/bin/env python3
"""Legal counsel time tracker — load a todo JSON and track daily project time."""

from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
import tkinter.messagebox as messagebox
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk

BG = "#F8F9FA"
TEXT = "#1A1A2E"
NAVY = "#2C3E6B"
BORDER = "#D1D5DB"
SELECTED_BG = "#E8ECF4"
SELECTED_BORDER = "#2C3E6B"
CLEAR_COLOR = "#8B3A3A"
MUTED = "#6B7280"
WHITE = "#FFFFFF"
WARN = "#B45309"

LOGS_DIR = Path(".time_logs")
SETTINGS_PATH = LOGS_DIR / "settings.json"

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "window_title": "Time Tracker — {date}",
        "elapsed": "Elapsed: {time}",
        "start": "Start",
        "end": "End",
        "clear": "Clear",
        "todo_header": "To do list for {date}:",
        "no_projects": "No projects found in the todo file.",
        "no_project_selected": "No project selected",
        "off_work": "Off work today!",
        "summary_title": "Completed work for {date}",
        "back": "Back",
        "no_description": "No description provided.",
        "time_used": "time used: {hours}",
        "edit": "Edit",
        "delete": "Delete",
        "add_project": "+ Add project",
        "edit_list": "Edit list",
        "done_editing": "Done",
        "save_list": "Save list",
        "saved": "Saved!",
        "unsaved_changes": "Unsaved changes",
        "edit_project_title": "Edit project",
        "add_project_title": "Add project",
        "project_name": "Project name",
        "items_label": "To-do items",
        "add_item": "+ Add item",
        "remove_item": "Remove",
        "ok": "OK",
        "cancel": "Cancel",
        "validation_name_required": "Project name is required.",
        "validation_item_required": "At least one to-do item is required.",
        "validation_duplicate_name": "A project with this name already exists.",
        "delete_title": "Delete project",
        "delete_confirm": "Delete \"{name}\" from the list?",
        "delete_with_time": (
            "Delete \"{name}\"? This project has {hours} of tracked time today."
        ),
        "unsaved_title": "Unsaved changes",
        "unsaved_message": "Save changes to the todo list before closing?",
    },
    "cn": {
        "window_title": "工时记录 — {date}",
        "elapsed": "已用时间：{time}",
        "start": "开始",
        "end": "结束",
        "clear": "清零",
        "todo_header": "{date} 待办清单：",
        "no_projects": "待办文件中没有项目。",
        "no_project_selected": "未选择项目",
        "off_work": "今日收工！",
        "summary_title": "{date} 已完成工作",
        "back": "返回",
        "no_description": "暂无工作描述。",
        "time_used": "用时：{hours}",
        "edit": "编辑",
        "delete": "删除",
        "add_project": "+ 添加项目",
        "edit_list": "编辑清单",
        "done_editing": "完成",
        "save_list": "保存清单",
        "saved": "已保存！",
        "unsaved_changes": "有未保存的更改",
        "edit_project_title": "编辑项目",
        "add_project_title": "添加项目",
        "project_name": "项目名称",
        "items_label": "待办事项",
        "add_item": "+ 添加事项",
        "remove_item": "移除",
        "ok": "确定",
        "cancel": "取消",
        "validation_name_required": "请输入项目名称。",
        "validation_item_required": "至少需要一个待办事项。",
        "validation_duplicate_name": "已存在同名项目。",
        "delete_title": "删除项目",
        "delete_confirm": "确定从清单中删除「{name}」？",
        "delete_with_time": "确定删除「{name}」？该项目今日已记录 {hours} 工时。",
        "unsaved_title": "未保存的更改",
        "unsaved_message": "关闭前是否保存待办清单的更改？",
    },
}


def normalize_language(value: str | None) -> str:
    if value and value.lower() in STRINGS:
        return value.lower()
    return "en"


def translate(lang: str, key: str, **kwargs: object) -> str:
    template = STRINGS[normalize_language(lang)][key]
    return template.format(**kwargs)


def load_language() -> str:
    if not SETTINGS_PATH.exists():
        return "en"
    try:
        with SETTINGS_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return normalize_language(data.get("language"))
    except (json.JSONDecodeError, OSError):
        return "en"


def save_language(lang: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"language": normalize_language(lang)}
    directory = SETTINGS_PATH.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        delete=False,
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        temp_path = handle.name
    os.replace(temp_path, SETTINGS_PATH)


@dataclass
class TodoItem:
    text: str
    done: bool = False


@dataclass
class TodoProject:
    name: str
    items: list[TodoItem] = field(default_factory=list)

    @property
    def description(self) -> str:
        texts = [item.text.strip() for item in self.items if item.text.strip()]
        return "; ".join(texts)

    @property
    def display_label(self) -> str:
        desc = self.description
        return f"{self.name}: {desc}" if desc else self.name


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_display_date(work_date: date, lang: str = "en") -> str:
    if normalize_language(lang) == "cn":
        return f"{work_date.year}年{work_date.month}月{work_date.day}日"
    return work_date.strftime("%d %b %Y")


def load_todo_document(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if "projects" not in data:
        raise ValueError("Todo file must contain a 'projects' key.")
    return data


def projects_from_document(data: dict) -> list[TodoProject]:
    projects: list[TodoProject] = []
    for entry in data.get("projects") or []:
        name = entry.get("name", "").strip()
        if not name:
            continue
        items = [
            TodoItem(
                text=item.get("text", "").strip(),
                done=bool(item.get("done", False)),
            )
            for item in (entry.get("items") or [])
        ]
        projects.append(TodoProject(name=name, items=items))
    return projects


def document_from_projects(base_doc: dict, projects: list[TodoProject]) -> dict:
    doc = copy.deepcopy(base_doc)
    doc["projects"] = [
        {
            "name": project.name,
            "items": [
                {"text": item.text, "done": item.done}
                for item in project.items
                if item.text.strip()
            ],
        }
        for project in projects
    ]
    doc["edited_at"] = datetime.now().isoformat(timespec="seconds")
    return doc


def save_todo_document(path: Path, doc: dict) -> None:
    directory = path.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        delete=False,
        suffix=".tmp",
    ) as handle:
        json.dump(doc, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temp_path = handle.name
    os.replace(temp_path, path)


def default_project_state() -> dict[str, Any]:
    return {
        "accumulated_seconds": 0,
        "is_running": False,
        "started_at": None,
    }


def load_daily_state(
    work_date: date,
    project_names: list[str],
    todo_source: str,
) -> dict[str, Any]:
    log_path = LOGS_DIR / f"{work_date.isoformat()}.json"
    state: dict[str, Any] = {
        "date": work_date.isoformat(),
        "todo_source": todo_source,
        "projects": {name: default_project_state() for name in project_names},
    }

    if not log_path.exists():
        return state

    with log_path.open(encoding="utf-8") as handle:
        stored = json.load(handle)

    if stored.get("date") != work_date.isoformat():
        return state

    stored_projects = stored.get("projects") or {}
    for name in project_names:
        if name not in stored_projects:
            continue
        entry = stored_projects[name]
        state["projects"][name] = {
            "accumulated_seconds": int(entry.get("accumulated_seconds", 0)),
            "is_running": bool(entry.get("is_running", False)),
            "started_at": entry.get("started_at"),
        }

    return state


def save_daily_state(
    work_date: date,
    todo_source: str,
    projects_state: dict[str, dict[str, Any]],
) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": work_date.isoformat(),
        "todo_source": todo_source,
        "projects": projects_state,
    }
    log_path = LOGS_DIR / f"{work_date.isoformat()}.json"
    directory = log_path.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        delete=False,
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        temp_path = handle.name
    os.replace(temp_path, log_path)


def get_elapsed_seconds(project_state: dict[str, Any], now: datetime) -> int:
    total = int(project_state.get("accumulated_seconds", 0))
    if project_state.get("is_running") and project_state.get("started_at"):
        started = datetime.fromisoformat(project_state["started_at"])
        total += max(0, int((now - started).total_seconds()))
    return total


def format_elapsed_hms(seconds: int, lang: str = "en") -> str:
    total = max(0, seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if normalize_language(lang) == "cn":
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}时")
        if minutes:
            parts.append(f"{minutes}分")
        parts.append(f"{secs}秒")
        return " ".join(parts)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def format_decimal_hours(seconds: int) -> str:
    hours = round(max(0, seconds) / 3600, 1)
    return f"{hours:.1f}h"


class TodoProjectDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        lang: str,
        project: TodoProject | None,
        existing_names: set[str],
        on_save: Callable[[TodoProject], None],
    ) -> None:
        super().__init__(parent)
        self.lang = normalize_language(lang)
        self.existing_names = existing_names
        self.on_save = on_save
        self.item_rows: list[tuple[ctk.CTkFrame, ctk.CTkEntry]] = []

        is_edit = project is not None
        self.title(
            translate(
                self.lang,
                "edit_project_title" if is_edit else "add_project_title",
            )
        )
        self.geometry("520x480")
        self.minsize(480, 420)
        self.configure(fg_color=BG)
        self.transient(parent)
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color=WHITE, border_width=1, border_color=BORDER)
        body.pack(fill="both", expand=True, padx=20, pady=20)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(3, weight=1)

        name_label = ctk.CTkLabel(
            body,
            text=translate(self.lang, "project_name"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        name_label.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))

        self.name_entry = ctk.CTkEntry(body, height=36, font=ctk.CTkFont(size=14))
        self.name_entry.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        if project is not None:
            self.name_entry.insert(0, project.name)

        items_label = ctk.CTkLabel(
            body,
            text=translate(self.lang, "items_label"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        items_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 6))

        self.items_scroll = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self.items_scroll.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.items_scroll.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(3, weight=1)

        if project is not None and project.items:
            for item in project.items:
                self._add_item_row(item.text)
        else:
            self._add_item_row("")

        self.error_label = ctk.CTkLabel(
            body,
            text="",
            text_color=CLEAR_COLOR,
            anchor="w",
            wraplength=440,
        )
        self.error_label.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 4))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=16, pady=(8, 16))
        actions.grid_columnconfigure(0, weight=1)

        add_item_btn = ctk.CTkButton(
            actions,
            text=translate(self.lang, "add_item"),
            width=120,
            height=32,
            fg_color=WHITE,
            text_color=NAVY,
            hover_color=SELECTED_BG,
            border_width=1,
            border_color=NAVY,
            font=ctk.CTkFont(size=13),
            command=lambda: self._add_item_row(""),
        )
        add_item_btn.grid(row=0, column=0, sticky="w")

        cancel_btn = ctk.CTkButton(
            actions,
            text=translate(self.lang, "cancel"),
            width=80,
            height=32,
            fg_color=WHITE,
            text_color=NAVY,
            hover_color=SELECTED_BG,
            border_width=1,
            border_color=NAVY,
            font=ctk.CTkFont(size=13),
            command=self.destroy,
        )
        cancel_btn.grid(row=0, column=2, padx=(8, 0))

        ok_btn = ctk.CTkButton(
            actions,
            text=translate(self.lang, "ok"),
            width=80,
            height=32,
            fg_color=NAVY,
            hover_color="#1F2D4D",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_ok,
        )
        ok_btn.grid(row=0, column=3, padx=(8, 0))

        self.bind("<Return>", lambda _event: self._on_ok())
        self.name_entry.focus_set()

    def _add_item_row(self, text: str) -> None:
        row = ctk.CTkFrame(self.items_scroll, fg_color=BG, corner_radius=6)
        row.grid(row=len(self.item_rows), column=0, sticky="ew", pady=4)
        row.grid_columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(row, height=32, font=ctk.CTkFont(size=13))
        entry.grid(row=0, column=0, sticky="ew", padx=(8, 8), pady=8)
        if text:
            entry.insert(0, text)

        remove_btn = ctk.CTkButton(
            row,
            text=translate(self.lang, "remove_item"),
            width=72,
            height=28,
            fg_color=WHITE,
            text_color=CLEAR_COLOR,
            hover_color="#F5EAEA",
            border_width=1,
            border_color=CLEAR_COLOR,
            font=ctk.CTkFont(size=12),
            command=lambda r=row: self._remove_item_row(r),
        )
        remove_btn.grid(row=0, column=1, padx=(0, 8), pady=8)

        self.item_rows.append((row, entry))

    def _remove_item_row(self, row: ctk.CTkFrame) -> None:
        self.item_rows = [(r, e) for r, e in self.item_rows if r is not row]
        row.destroy()
        for index, (item_row, _) in enumerate(self.item_rows):
            item_row.grid(row=index, column=0, sticky="ew", pady=4)

    def _show_error(self, message: str) -> None:
        self.error_label.configure(text=message)

    def _on_ok(self) -> None:
        name = self.name_entry.get().strip()
        if not name:
            self._show_error(translate(self.lang, "validation_name_required"))
            return

        item_texts = [entry.get().strip() for _, entry in self.item_rows]
        non_empty = [text for text in item_texts if text]
        if not non_empty:
            self._show_error(translate(self.lang, "validation_item_required"))
            return

        if name in self.existing_names:
            self._show_error(translate(self.lang, "validation_duplicate_name"))
            return

        project = TodoProject(
            name=name,
            items=[TodoItem(text=text, done=False) for text in non_empty],
        )
        self.on_save(project)
        self.destroy()


class TimeTrackerApp(ctk.CTk):
    def __init__(
        self,
        projects: list[TodoProject],
        work_date: date,
        todo_path: Path,
        daily_state: dict[str, Any],
        todo_document: dict,
        lang: str = "en",
    ) -> None:
        super().__init__()
        self.projects = projects
        self.work_date = work_date
        self.todo_path = todo_path
        self.todo_source = todo_path.name
        self.todo_document = todo_document
        self.todo_dirty = False
        self.todo_edit_controls_visible = False
        self.projects_state: dict[str, dict[str, Any]] = daily_state["projects"]
        self.lang = normalize_language(lang)
        self.selected_index = 0 if projects else -1
        self.todo_row_frames: list[ctk.CTkFrame] = []
        self.empty_label: ctk.CTkLabel | None = None

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.geometry("900x650")
        self.minsize(760, 580)
        self.configure(fg_color=BG)

        self.container = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.container.pack(fill="both", expand=True, padx=24, pady=24)

        self.tracker_frame = ctk.CTkFrame(self.container, fg_color=BG, corner_radius=0)
        self.summary_frame = ctk.CTkFrame(self.container, fg_color=BG, corner_radius=0)

        self._build_tracker_view()
        self._build_summary_view()
        self._show_tracker()
        self._apply_language()
        self._tick()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _t(self, key: str, **kwargs: object) -> str:
        return translate(self.lang, key, **kwargs)

    def _display_date(self) -> str:
        return format_display_date(self.work_date, self.lang)

    def _apply_language(self) -> None:
        self.lang_selector.set("EN" if self.lang == "en" else "CN")
        self.title(self._t("window_title", date=self._display_date()))
        self.todo_header.configure(text=self._t("todo_header", date=self._display_date()))
        self.clear_button.configure(text=self._t("clear"))
        self.add_project_button.configure(text=self._t("add_project"))
        self.edit_list_button.configure(text=self._t("edit_list"))
        self.done_editing_button.configure(text=self._t("done_editing"))
        if not self.todo_dirty:
            self.save_list_button.configure(text=self._t("save_list"))
        self.off_work_button.configure(text=self._t("off_work"))
        self.summary_title.configure(text=self._t("summary_title", date=self._display_date()))
        self.back_button.configure(text=self._t("back"))
        self._refresh_todo_edit_controls()
        self._refresh_active_panel()
        if self.summary_frame.winfo_ismapped():
            self._render_summary()

    def _on_language_change(self, value: str) -> None:
        self.lang = "cn" if value == "CN" else "en"
        save_language(self.lang)
        self._apply_language()

    def _selected_project(self) -> TodoProject | None:
        if self.selected_index < 0 or self.selected_index >= len(self.projects):
            return None
        return self.projects[self.selected_index]

    def _project_state(self, name: str) -> dict[str, Any]:
        if name not in self.projects_state:
            self.projects_state[name] = default_project_state()
        return self.projects_state[name]

    def _save_state(self) -> None:
        save_daily_state(self.work_date, self.todo_source, self.projects_state)

    def _mark_dirty(self) -> None:
        self.todo_dirty = True
        self.todo_edit_controls_visible = True
        self._refresh_dirty_indicator()
        self._refresh_todo_edit_controls()

    def _refresh_dirty_indicator(self) -> None:
        if self.todo_dirty:
            self.unsaved_label.configure(text=self._t("unsaved_changes"))
        else:
            self.unsaved_label.configure(text="")
        save_state = "normal" if self.todo_dirty else "disabled"
        self.save_list_button.configure(state=save_state)

    def _on_enter_edit_mode(self) -> None:
        self.todo_edit_controls_visible = True
        self._refresh_todo_edit_controls()

    def _on_done_editing(self) -> None:
        if self.todo_dirty:
            return
        self.todo_edit_controls_visible = False
        self._refresh_todo_edit_controls()

    def _refresh_todo_edit_controls(self) -> None:
        self.edit_list_button.grid_remove()
        self.add_project_button.grid_remove()
        self.done_editing_button.grid_remove()
        self.save_list_button.grid_remove()

        if self.todo_edit_controls_visible:
            self.add_project_button.grid(row=0, column=2, padx=(0, 8), sticky="e")
            if self.todo_dirty:
                self.save_list_button.grid(row=0, column=3, padx=(0, 8), sticky="e")
            else:
                self.done_editing_button.grid(row=0, column=3, padx=(0, 8), sticky="e")
        else:
            self.edit_list_button.grid(row=0, column=2, padx=(0, 8), sticky="e")

        self._rebuild_todo_list()

    def _save_todo_list(self) -> None:
        doc = document_from_projects(self.todo_document, self.projects)
        save_todo_document(self.todo_path, doc)
        self.todo_document = doc
        self.todo_dirty = False
        self.todo_edit_controls_visible = False
        self._refresh_dirty_indicator()
        self._refresh_todo_edit_controls()
        self.unsaved_label.configure(text=self._t("saved"), text_color=NAVY)
        self.after(
            2000,
            lambda: self.unsaved_label.configure(text="", text_color=WARN),
        )

    def _end_project(self, name: str) -> None:
        state = self._project_state(name)
        if not state.get("is_running"):
            return
        now = datetime.now()
        elapsed = get_elapsed_seconds(state, now)
        state["accumulated_seconds"] = elapsed
        state["is_running"] = False
        state["started_at"] = None

    def _end_all_running(self) -> None:
        for name, state in self.projects_state.items():
            if state.get("is_running"):
                self._end_project(name)

    def _start_project(self, name: str) -> None:
        self._end_all_running()
        state = self._project_state(name)
        state["is_running"] = True
        state["started_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state()
        self._refresh_active_panel()

    def _clear_project(self, name: str) -> None:
        self._end_project(name)
        state = self._project_state(name)
        state["accumulated_seconds"] = 0
        self._save_state()
        self._refresh_active_panel()

    def _migrate_project_state(self, old_name: str, new_name: str) -> None:
        if old_name == new_name:
            return
        self._end_project(old_name)
        if old_name in self.projects_state:
            self.projects_state[new_name] = self.projects_state.pop(old_name)
        else:
            self.projects_state[new_name] = default_project_state()

    def _select_project(self, index: int) -> None:
        if index < 0 or index >= len(self.projects):
            return
        if index == self.selected_index:
            return
        self._end_all_running()
        self.selected_index = index
        self._save_state()
        self._refresh_todo_selection()
        self._refresh_active_panel()

    def _existing_names_excluding(self, index: int | None) -> set[str]:
        names: set[str] = set()
        for idx, project in enumerate(self.projects):
            if index is not None and idx == index:
                continue
            names.add(project.name)
        return names

    def _open_project_dialog(
        self,
        index: int | None,
        project: TodoProject | None,
    ) -> None:
        existing = self._existing_names_excluding(index)

        def on_save(updated: TodoProject) -> None:
            if index is None:
                self.projects.append(updated)
                self.projects_state[updated.name] = default_project_state()
                self.selected_index = len(self.projects) - 1
            else:
                old_name = self.projects[index].name
                if old_name != updated.name:
                    self._migrate_project_state(old_name, updated.name)
                self.projects[index] = updated
            self._mark_dirty()
            self._set_controls_enabled(bool(self.projects))
            self._refresh_active_panel()
            self._save_state()

        TodoProjectDialog(self, self.lang, project, existing, on_save)

    def _on_edit_project(self, index: int) -> None:
        if index < 0 or index >= len(self.projects):
            return
        self._open_project_dialog(index, self.projects[index])

    def _on_add_project(self) -> None:
        self._open_project_dialog(None, None)

    def _confirm_delete_project(self, project: TodoProject) -> bool:
        seconds = get_elapsed_seconds(
            self._project_state(project.name),
            datetime.now(),
        )
        if seconds > 0:
            message = self._t(
                "delete_with_time",
                name=project.name,
                hours=format_decimal_hours(seconds),
            )
        else:
            message = self._t("delete_confirm", name=project.name)
        return messagebox.askyesno(self._t("delete_title"), message)

    def _on_delete_project(self, index: int) -> None:
        if index < 0 or index >= len(self.projects):
            return
        project = self.projects[index]
        if not self._confirm_delete_project(project):
            return

        self._end_project(project.name)
        del self.projects[index]
        self.projects_state.pop(project.name, None)

        if self.selected_index == index:
            self.selected_index = min(index, len(self.projects) - 1)
        elif self.selected_index > index:
            self.selected_index -= 1
        if not self.projects:
            self.selected_index = -1

        self._mark_dirty()
        self._set_controls_enabled(bool(self.projects))
        self._refresh_active_panel()
        self._save_state()

    def _build_tracker_view(self) -> None:
        self.tracker_frame.grid_columnconfigure(0, weight=1)
        self.tracker_frame.grid_rowconfigure(2, weight=1)

        lang_header = ctk.CTkFrame(self.tracker_frame, fg_color="transparent")
        lang_header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        lang_header.grid_columnconfigure(0, weight=1)

        self.lang_selector = ctk.CTkSegmentedButton(
            lang_header,
            values=["EN", "CN"],
            width=120,
            height=32,
            font=ctk.CTkFont(size=13),
            fg_color=WHITE,
            selected_color=NAVY,
            selected_hover_color="#1F2D4D",
            unselected_color=WHITE,
            unselected_hover_color=SELECTED_BG,
            text_color=NAVY,
            command=self._on_language_change,
        )
        self.lang_selector.set("EN" if self.lang == "en" else "CN")
        self.lang_selector.grid(row=0, column=1, sticky="e")

        active_panel = ctk.CTkFrame(
            self.tracker_frame,
            fg_color=WHITE,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
        )
        active_panel.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        active_panel.grid_columnconfigure(0, weight=1)
        active_panel.grid_columnconfigure(1, weight=0)

        self.project_label = ctk.CTkLabel(
            active_panel,
            text="",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT,
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self.project_label.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 8))

        self.elapsed_label = ctk.CTkLabel(
            active_panel,
            text="",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=NAVY,
            anchor="w",
        )
        self.elapsed_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 24))

        button_panel = ctk.CTkFrame(active_panel, fg_color="transparent")
        button_panel.grid(row=0, column=1, rowspan=2, padx=24, pady=24)

        self.toggle_button = ctk.CTkButton(
            button_panel,
            text="",
            width=88,
            height=88,
            corner_radius=44,
            fg_color=NAVY,
            hover_color="#1F2D4D",
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._on_toggle,
        )
        self.toggle_button.pack(pady=(0, 10))

        self.clear_button = ctk.CTkButton(
            button_panel,
            text="",
            width=88,
            height=88,
            corner_radius=44,
            fg_color=WHITE,
            text_color=CLEAR_COLOR,
            hover_color="#F5EAEA",
            border_width=2,
            border_color=CLEAR_COLOR,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._on_clear,
        )
        self.clear_button.pack()

        todo_panel = ctk.CTkFrame(
            self.tracker_frame,
            fg_color=WHITE,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
        )
        todo_panel.grid(row=2, column=0, sticky="nsew")
        todo_panel.grid_columnconfigure(0, weight=1)
        todo_panel.grid_rowconfigure(1, weight=1)

        self.todo_header = ctk.CTkLabel(
            todo_panel,
            text="",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        self.todo_header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))

        self.todo_scroll = ctk.CTkScrollableFrame(
            todo_panel,
            fg_color="transparent",
            corner_radius=0,
        )
        self.todo_scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.todo_scroll.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkFrame(todo_panel, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(8, 20))
        footer.grid_columnconfigure(0, weight=1)

        self.unsaved_label = ctk.CTkLabel(
            footer,
            text="",
            text_color=WARN,
            font=ctk.CTkFont(size=13),
            anchor="w",
        )
        self.unsaved_label.grid(row=0, column=0, sticky="w")

        self.off_work_button = ctk.CTkButton(
            footer,
            text="",
            width=160,
            height=40,
            fg_color=NAVY,
            hover_color="#1F2D4D",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._show_summary,
        )
        self.off_work_button.grid(row=0, column=4, sticky="e")

        self.save_list_button = ctk.CTkButton(
            footer,
            text="",
            width=120,
            height=40,
            fg_color=WHITE,
            text_color=NAVY,
            hover_color=SELECTED_BG,
            border_width=1,
            border_color=NAVY,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._save_todo_list,
            state="disabled",
        )
        self.save_list_button.grid(row=0, column=3, padx=(0, 8), sticky="e")

        self.edit_list_button = ctk.CTkButton(
            footer,
            text="",
            width=120,
            height=40,
            fg_color=WHITE,
            text_color=NAVY,
            hover_color=SELECTED_BG,
            border_width=1,
            border_color=NAVY,
            font=ctk.CTkFont(size=14),
            command=self._on_enter_edit_mode,
        )

        self.add_project_button = ctk.CTkButton(
            footer,
            text="",
            width=140,
            height=40,
            fg_color=WHITE,
            text_color=NAVY,
            hover_color=SELECTED_BG,
            border_width=1,
            border_color=NAVY,
            font=ctk.CTkFont(size=14),
            command=self._on_add_project,
        )

        self.done_editing_button = ctk.CTkButton(
            footer,
            text="",
            width=80,
            height=40,
            fg_color=WHITE,
            text_color=NAVY,
            hover_color=SELECTED_BG,
            border_width=1,
            border_color=NAVY,
            font=ctk.CTkFont(size=14),
            command=self._on_done_editing,
        )

        self._refresh_todo_edit_controls()
        self._set_controls_enabled(bool(self.projects))

    def _rebuild_todo_list(self) -> None:
        for widget in self.todo_scroll.winfo_children():
            widget.destroy()
        self.todo_row_frames.clear()
        self.empty_label = None

        if not self.projects:
            self.empty_label = ctk.CTkLabel(
                self.todo_scroll,
                text=self._t("no_projects"),
                text_color=MUTED,
                anchor="w",
            )
            self.empty_label.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        else:
            for index, project in enumerate(self.projects):
                row = self._create_todo_row(index, project)
                row.grid(row=index, column=0, sticky="ew", pady=4)
                self.todo_row_frames.append(row)

        self._refresh_todo_selection()

    def _create_todo_row(self, index: int, project: TodoProject) -> ctk.CTkFrame:
        row = ctk.CTkFrame(
            self.todo_scroll,
            fg_color=BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=8,
        )
        row.grid_columnconfigure(0, weight=1)

        label = ctk.CTkLabel(
            row,
            text=f"{index + 1}. {project.display_label}",
            font=ctk.CTkFont(size=14),
            text_color=TEXT,
            anchor="w",
            justify="left",
            wraplength=560,
        )
        label_padx = (16, 8) if self.todo_edit_controls_visible else (16, 16)
        label.grid(row=0, column=0, sticky="ew", padx=label_padx, pady=12)

        if self.todo_edit_controls_visible:
            edit_btn = ctk.CTkButton(
                row,
                text=self._t("edit"),
                width=64,
                height=28,
                fg_color=WHITE,
                text_color=NAVY,
                hover_color=SELECTED_BG,
                border_width=1,
                border_color=NAVY,
                font=ctk.CTkFont(size=12),
                command=lambda idx=index: self._on_edit_project(idx),
            )
            edit_btn.grid(row=0, column=1, padx=(0, 4), pady=8)

            delete_btn = ctk.CTkButton(
                row,
                text=self._t("delete"),
                width=64,
                height=28,
                fg_color=WHITE,
                text_color=CLEAR_COLOR,
                hover_color="#F5EAEA",
                border_width=1,
                border_color=CLEAR_COLOR,
                font=ctk.CTkFont(size=12),
                command=lambda idx=index: self._on_delete_project(idx),
            )
            delete_btn.grid(row=0, column=2, padx=(0, 12), pady=8)

        def on_click(_event=None, idx=index) -> None:
            self._select_project(idx)

        for widget in (row, label):
            widget.bind("<Button-1>", on_click)
            widget.configure(cursor="hand2")

        return row

    def _refresh_todo_selection(self) -> None:
        for index, row in enumerate(self.todo_row_frames):
            selected = index == self.selected_index
            row.configure(
                fg_color=SELECTED_BG if selected else BG,
                border_color=SELECTED_BORDER if selected else BORDER,
            )

    def _refresh_active_panel(self) -> None:
        project = self._selected_project()
        if project is None:
            self.project_label.configure(text=self._t("no_project_selected"))
            self.elapsed_label.configure(
                text=self._t("elapsed", time=format_elapsed_hms(0, self.lang))
            )
            return

        self.project_label.configure(text=project.display_label)
        elapsed = get_elapsed_seconds(self._project_state(project.name), datetime.now())
        self.elapsed_label.configure(
            text=self._t("elapsed", time=format_elapsed_hms(elapsed, self.lang))
        )

        running = self._project_state(project.name).get("is_running", False)
        if running:
            self.toggle_button.configure(
                text=self._t("end"),
                fg_color=WHITE,
                text_color=NAVY,
                hover_color=SELECTED_BG,
                border_width=2,
                border_color=NAVY,
            )
        else:
            self.toggle_button.configure(
                text=self._t("start"),
                fg_color=NAVY,
                text_color=WHITE,
                hover_color="#1F2D4D",
                border_width=0,
                border_color=NAVY,
            )

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.toggle_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.off_work_button.configure(state=state)

    def _on_toggle(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        if self._project_state(project.name).get("is_running", False):
            self._end_project(project.name)
            self._save_state()
            self._refresh_active_panel()
        else:
            self._start_project(project.name)

    def _on_clear(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        self._clear_project(project.name)

    def _build_summary_view(self) -> None:
        self.summary_frame.grid_columnconfigure(0, weight=1)
        self.summary_frame.grid_rowconfigure(1, weight=1)

        header_row = ctk.CTkFrame(self.summary_frame, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header_row.grid_columnconfigure(0, weight=1)

        self.summary_title = ctk.CTkLabel(
            header_row,
            text="",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        self.summary_title.grid(row=0, column=0, sticky="w")

        self.back_button = ctk.CTkButton(
            header_row,
            text="",
            width=80,
            height=32,
            fg_color=WHITE,
            text_color=NAVY,
            hover_color=SELECTED_BG,
            border_width=1,
            border_color=NAVY,
            font=ctk.CTkFont(size=13),
            command=self._show_tracker,
        )
        self.back_button.grid(row=0, column=1, sticky="e")

        self.summary_scroll = ctk.CTkScrollableFrame(
            self.summary_frame,
            fg_color=WHITE,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
        )
        self.summary_scroll.grid(row=1, column=0, sticky="nsew")
        self.summary_scroll.grid_columnconfigure(0, weight=1)

    def _render_summary(self) -> None:
        for widget in self.summary_scroll.winfo_children():
            widget.destroy()

        now = datetime.now()
        for index, project in enumerate(self.projects):
            seconds = get_elapsed_seconds(self._project_state(project.name), now)
            block = ctk.CTkFrame(
                self.summary_scroll,
                fg_color=BG if index % 2 == 0 else WHITE,
                corner_radius=8,
            )
            block.grid(row=index, column=0, sticky="ew", padx=16, pady=8)
            block.grid_columnconfigure(0, weight=1)

            title = ctk.CTkLabel(
                block,
                text=f"{index + 1}. {project.name}",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=TEXT,
                anchor="w",
            )
            title.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))

            description = project.description or self._t("no_description")
            desc_label = ctk.CTkLabel(
                block,
                text=description,
                font=ctk.CTkFont(size=14),
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=760,
            )
            desc_label.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 4))

            time_label = ctk.CTkLabel(
                block,
                text=self._t("time_used", hours=format_decimal_hours(seconds)),
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=NAVY,
                anchor="w",
            )
            time_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))

    def _show_tracker(self) -> None:
        self.summary_frame.grid_forget()
        self.tracker_frame.grid(row=0, column=0, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)
        self._refresh_todo_selection()
        self._refresh_active_panel()

    def _show_summary(self) -> None:
        self._end_all_running()
        self._save_state()
        self._render_summary()
        self.tracker_frame.grid_forget()
        self.summary_frame.grid(row=0, column=0, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

    def _tick(self) -> None:
        if self.tracker_frame.winfo_ismapped():
            self._refresh_active_panel()
        self.after(1000, self._tick)

    def _on_close(self) -> None:
        if self.todo_dirty:
            result = messagebox.askyesnocancel(
                self._t("unsaved_title"),
                self._t("unsaved_message"),
            )
            if result is None:
                return
            if result:
                self._save_todo_list()
        self._end_all_running()
        self._save_state()
        self.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Track daily time spent on projects from an email-generated todo list.",
    )
    parser.add_argument(
        "todo_file",
        type=Path,
        help="Path to the todo JSON file (e.g. emails_2026-06-06_2026-06-07_todo.json).",
    )
    parser.add_argument(
        "--date",
        type=parse_date,
        default=None,
        help="Override today's date for testing (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--lang",
        choices=["en", "cn"],
        default=None,
        help="UI language (en or cn). Overrides saved preference.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    todo_path = args.todo_file.resolve()
    if not todo_path.exists():
        raise SystemExit(f"Todo file not found: {todo_path}")

    todo_document = load_todo_document(todo_path)
    projects = projects_from_document(todo_document)
    work_date = args.date or date.today()
    lang = normalize_language(args.lang) if args.lang else load_language()
    daily_state = load_daily_state(
        work_date,
        [project.name for project in projects],
        todo_path.name,
    )

    app = TimeTrackerApp(
        projects,
        work_date,
        todo_path,
        daily_state,
        todo_document,
        lang=lang,
    )
    app.mainloop()


if __name__ == "__main__":
    main()
