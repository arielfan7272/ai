#!/usr/bin/env python3
"""Legal counsel time tracker — load a todo JSON and track daily project time."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
    },
}


def normalize_language(value: str | None) -> str:
    if value and value.lower() in STRINGS:
        return value.lower()
    return "en"


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
class Project:
    name: str
    description: str
    display_label: str


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_display_date(work_date: date, lang: str = "en") -> str:
    if normalize_language(lang) == "cn":
        return f"{work_date.year}年{work_date.month}月{work_date.day}日"
    return work_date.strftime("%d %b %Y")


def load_todo(path: Path) -> list[Project]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if "projects" not in data:
        raise ValueError("Todo file must contain a 'projects' key.")

    projects: list[Project] = []
    for entry in data["projects"]:
        name = entry.get("name", "").strip()
        if not name:
            continue
        items = entry.get("items") or []
        texts = [item.get("text", "").strip() for item in items if item.get("text")]
        description = "; ".join(texts)
        display_label = f"{name}: {description}" if description else name
        projects.append(Project(name=name, description=description, display_label=display_label))

    return projects


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


class TimeTrackerApp(ctk.CTk):
    def __init__(
        self,
        projects: list[Project],
        work_date: date,
        todo_source: str,
        daily_state: dict[str, Any],
        lang: str = "en",
    ) -> None:
        super().__init__()
        self.projects = projects
        self.work_date = work_date
        self.todo_source = todo_source
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
        template = STRINGS[self.lang][key]
        return template.format(**kwargs)

    def _display_date(self) -> str:
        return format_display_date(self.work_date, self.lang)

    def _apply_language(self) -> None:
        self.lang_selector.set("EN" if self.lang == "en" else "CN")
        self.title(self._t("window_title", date=self._display_date()))
        self.todo_header.configure(text=self._t("todo_header", date=self._display_date()))
        self.clear_button.configure(text=self._t("clear"))
        self.off_work_button.configure(text=self._t("off_work"))
        self.summary_title.configure(text=self._t("summary_title", date=self._display_date()))
        self.back_button.configure(text=self._t("back"))
        if self.empty_label is not None:
            self.empty_label.configure(text=self._t("no_projects"))
        self._refresh_active_panel()
        if self.summary_frame.winfo_ismapped():
            self._render_summary()

    def _on_language_change(self, value: str) -> None:
        self.lang = "cn" if value == "CN" else "en"
        save_language(self.lang)
        self._apply_language()

    def _selected_project(self) -> Project | None:
        if self.selected_index < 0 or self.selected_index >= len(self.projects):
            return None
        return self.projects[self.selected_index]

    def _project_state(self, name: str) -> dict[str, Any]:
        return self.projects_state[name]

    def _save_state(self) -> None:
        save_daily_state(self.work_date, self.todo_source, self.projects_state)

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

        if not self.projects:
            self.empty_label = ctk.CTkLabel(
                self.todo_scroll,
                text="",
                text_color=MUTED,
                anchor="w",
            )
            self.empty_label.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        else:
            for index, project in enumerate(self.projects):
                row = self._create_todo_row(index, project)
                row.grid(row=index, column=0, sticky="ew", pady=4)
                self.todo_row_frames.append(row)

        footer = ctk.CTkFrame(todo_panel, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(8, 20))
        footer.grid_columnconfigure(0, weight=1)

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
        self.off_work_button.grid(row=0, column=1, sticky="e")

        self._set_controls_enabled(bool(self.projects))

    def _create_todo_row(self, index: int, project: Project) -> ctk.CTkFrame:
        row = ctk.CTkFrame(
            self.todo_scroll,
            fg_color=BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=8,
            height=52,
        )
        row.grid_columnconfigure(0, weight=1)

        label = ctk.CTkLabel(
            row,
            text=f"{index + 1}. {project.display_label}",
            font=ctk.CTkFont(size=14),
            text_color=TEXT,
            anchor="w",
            justify="left",
            wraplength=760,
        )
        label.grid(row=0, column=0, sticky="ew", padx=16, pady=12)

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

    projects = load_todo(todo_path)
    work_date = args.date or date.today()
    lang = normalize_language(args.lang) if args.lang else load_language()
    daily_state = load_daily_state(
        work_date,
        [project.name for project in projects],
        todo_path.name,
    )

    app = TimeTrackerApp(projects, work_date, todo_path.name, daily_state, lang=lang)
    app.mainloop()


if __name__ == "__main__":
    main()
