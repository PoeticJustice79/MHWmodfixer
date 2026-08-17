"""
MHWmodfixer by Littlefish (PoeticJustice79) -- GUI front-end.

Mod archives can be dropped onto the window (or picked via the file
dialog, multi-select is fine too) and are queued up; "Start Repair" walks
the queue and fixes them one at a time, in order. Each one still gets its
own "here's what's stale, proceed?" confirmation and its own "where do you
want to save the result?" prompt, same as the single-file flow -- just
looped automatically instead of requiring the file to be re-picked by hand
each time.

UI chrome (labels/buttons/status/dialogs) is localized via i18n.py; the
detailed processing log (donor-matching, staleness diagnosis, etc.) is
deliberately NOT translated -- see i18n.py's module docstring for why.
"""
from __future__ import annotations

import datetime
import os
import queue
import shutil
import tempfile
import threading
import traceback
import zipfile
from pathlib import Path

import tkinter as tk
from tkinter import BooleanVar, StringVar, filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

import i18n
import rsz_layout
from archive_extract import PasswordRequired, extract_archive
from auto_fix import DEFAULT_GAME_DIR, DEFAULT_FLUFFY_DIR, auto_detect_fluffy_dir, process_mod
from diagnose import diagnose, summarize
from fluffy_repackage import needs_repackaging, repackage_for_fluffy
from game_archive import GameArchive
from i18n import t

# Bump this by hand at release time -- not something to change unprompted
# (versioning is the maintainer's call, not something automated here).
APP_VERSION = "v0.5"
APP_TITLE = f"MHWmodfixer {APP_VERSION} by Littlefish (PoeticJustice79)"
ARCHIVE_EXTS = {".zip", ".7z", ".rar"}
LOG_DIR = Path.home() / "AppData" / "Local" / "MHWmodfixer" / "logs"

# "Night Ops" palette -- user-picked direction (of three mockups shown as an
# artifact, 2026-08-09) out of a warm-light/dark-ember/cool-slate set. Only
# covers what this app can actually restyle: the main window's own widgets
# and the one Toplevel dialog (RSZ Snapshot). tkinter.messagebox dialogs
# (confirmations, errors) stay native OS chrome regardless -- there's no
# supported way to theme those, and reimplementing them as custom Toplevels
# just to recolor them isn't worth the added surface area.
THEME = {
    "bg": "#17160f", "surface": "#1e1c14", "surface_alt": "#241f14",
    "ink": "#ede6d3", "muted": "#93876e", "border": "#322e1f",
    "input_bg": "#1b1911",
    "btn_bg": "#211e14", "btn_hover": "#2c291b", "btn_active": "#332f1e",
    "accent": "#dd8339", "accent_hover": "#c9722c", "accent_ink": "#17160f",
    "warn": "#e0a83f", "success": "#86b98f", "danger": "#e2685a",
    "progress_track": "#2a271a", "log_bg": "#100f0a",
}


def _apply_theme(root: tk.Tk) -> ttk.Style:
    """Switches to the 'clam' base ttk theme (the only built-in theme that
    honors arbitrary color configuration on Windows -- 'vista' looks native
    but silently ignores most style.configure() color overrides, since it
    delegates rendering to the OS theme engine) and recolors every ttk
    widget class this app actually uses to the Night Ops palette. Returns
    the Style object in case a caller needs it (currently unused)."""
    th = THEME
    root.configure(bg=th["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=th["bg"], foreground=th["ink"],
                     fieldbackground=th["input_bg"], bordercolor=th["border"],
                     darkcolor=th["bg"], lightcolor=th["bg"], troughcolor=th["progress_track"])
    style.configure("TFrame", background=th["bg"])
    style.configure("TLabel", background=th["bg"], foreground=th["ink"])
    style.configure("TButton", background=th["btn_bg"], foreground=th["ink"],
                     bordercolor=th["border"], focuscolor=th["accent"], padding=(10, 5))
    style.map("TButton",
              background=[("active", th["btn_hover"]), ("pressed", th["btn_active"]), ("disabled", th["bg"])],
              foreground=[("disabled", th["muted"])])
    style.configure("TMenubutton", background=th["btn_bg"], foreground=th["ink"],
                     bordercolor=th["border"], arrowcolor=th["ink"], padding=(10, 5))
    style.map("TMenubutton", background=[("active", th["btn_hover"])])
    style.configure("TCheckbutton", background=th["bg"], foreground=th["ink"])
    style.map("TCheckbutton", background=[("active", th["bg"])], foreground=[("disabled", th["muted"])])
    style.configure("TEntry", fieldbackground=th["input_bg"], foreground=th["ink"],
                     insertcolor=th["ink"], bordercolor=th["border"])
    style.configure("TCombobox", fieldbackground=th["input_bg"], background=th["btn_bg"],
                     foreground=th["ink"], arrowcolor=th["ink"], bordercolor=th["border"])
    style.map("TCombobox", fieldbackground=[("readonly", th["input_bg"])],
              foreground=[("readonly", th["ink"])])
    root.option_add("*TCombobox*Listbox.background", th["surface"])
    root.option_add("*TCombobox*Listbox.foreground", th["ink"])
    root.option_add("*TCombobox*Listbox.selectBackground", th["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", th["accent_ink"])
    style.configure("TLabelframe", background=th["bg"], bordercolor=th["border"])
    style.configure("TLabelframe.Label", background=th["bg"], foreground=th["warn"])
    style.configure("TScrollbar", background=th["btn_bg"], troughcolor=th["bg"],
                     bordercolor=th["border"], arrowcolor=th["ink"])
    style.map("TScrollbar", background=[("active", th["btn_hover"])])
    style.configure("TProgressbar", background=th["accent"], troughcolor=th["progress_track"],
                     bordercolor=th["border"], lightcolor=th["accent"], darkcolor=th["accent"])
    style.configure("Treeview", background=th["input_bg"], fieldbackground=th["input_bg"],
                     foreground=th["ink"], bordercolor=th["border"], rowheight=22)
    style.map("Treeview", background=[("selected", th["accent"])],
              foreground=[("selected", th["accent_ink"])])
    style.configure("Treeview.Heading", background=th["surface_alt"], foreground=th["muted"],
                     bordercolor=th["border"], relief="flat")
    style.map("Treeview.Heading", background=[("active", th["surface_alt"])])
    return style


class _Tooltip:
    """A small delayed popup shown while hovering `widget`, its text
    supplied by `text_fn()` (called fresh on each hover so it can react to
    the current language). Used for the ⓘ info glyph next to
    "적용 방어구 변경" -- that button's own label stays short per the
    user's request, with the full explanation only a hover away."""

    def __init__(self, widget, text_fn, wraplength=340):
        self.widget = widget
        self.text_fn = text_fn
        self.wraplength = wraplength
        self._tip = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        self._after_id = None

    def _schedule(self, _event=None):
        self._after_id = self.widget.after(400, self._show)

    def _show(self):
        if self._tip is not None:
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self.text_fn(), justify="left", wraplength=self.wraplength,
                 background=THEME["surface_alt"], foreground=THEME["ink"],
                 borderwidth=1, relief="solid", padx=8, pady=6,
                 font=("Segoe UI", 9)).pack()

    def _hide(self, _event=None):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def _log_tag_for(msg: str) -> str | None:
    """Which Text tag (see log_text.tag_configure() calls in _build_ui())
    a log line should render with, based on the [fixed]/[warn]/[error]/etc.
    markers this project's own log() callers already use consistently
    throughout pfb_fix.py/auto_fix.py/pak_mod_fix.py/mesh_check.py -- purely
    a display concern, never re-interprets or filters what gets logged."""
    low = msg.lower()
    if "[error]" in low or "traceback" in low:
        return "logerror"
    if "[warn]" in low:
        return "logwarn"
    if "[fixed]" in low or "[ok]" in low:
        return "logok"
    if "[info]" in low or "[skip]" in low or "[kept as shipped]" in low:
        return "logdim"
    return None


def zip_folder(src_folder: Path, dest_zip: Path):
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in src_folder.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(src_folder))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("760x640")
        root.minsize(600, 460)

        i18n.set_language(i18n.load_saved_language())

        self.game_dir = StringVar(value=DEFAULT_GAME_DIR if Path(DEFAULT_GAME_DIR).is_dir() else "")
        _fluffy_default = auto_detect_fluffy_dir() or (DEFAULT_FLUFFY_DIR if Path(DEFAULT_FLUFFY_DIR).is_dir() else "")
        self.fluffy_dir = StringVar(value=_fluffy_default)
        self.status = StringVar(value=t("status_default"))
        self.lang_display = StringVar(value=i18n.LANGUAGES[i18n.get_language()])
        self.force_unresolved = BooleanVar(value=False)
        self.preserve_extra = BooleanVar(value=False)
        self.shader_migration = BooleanVar(value=False)
        self.mod_queue: list[Path] = []
        self._retarget_refresh_fn = None  # set while the retarget dialog is open, see _open_retarget_dialog()
        self._weapon_retarget_refresh_fn = None  # see _open_weapon_retarget_dialog()
        self._snapshot_refresh_fn = None  # set while the RSZ snapshot dialog is open, see _open_snapshot_dialog()

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._main_thread_queue: queue.Queue[tuple] = queue.Queue()
        self._progress_queue: queue.Queue[tuple[str, int, int]] = queue.Queue()
        self._busy = False

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log_file_path = LOG_DIR / f"mhwmodfixer_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
        self._log_fh = open(self.log_file_path, "a", encoding="utf-8")

        self._build_ui()
        self._poll_queues()
        self.log(f"[log file] {self.log_file_path}")

    # ---- UI layout ---------------------------------------------------

    def _build_menubar(self):
        # NOT a native root-level menu bar (tried that first: `root.config(
        # menu=...)` draws as opaque OS chrome on Windows regardless of any
        # tk.Menu color kwargs -- a stark white strip across the top of an
        # otherwise dark window, confirmed visually once actually launched).
        # A ttk.Menubutton's dropdown is a genuinely separate floating
        # popup, not part of the window frame, so IT does honor tk.Menu
        # color kwargs on Windows -- this gets the identical two-level
        # Settings > Developer Options > RSZ Snapshot structure fully
        # themed instead. Rebuilt from scratch on every language change
        # (not entryconfigure()'d in place) since that's what already
        # worked reliably for the old native menu and there's no reason to
        # risk the same "-label" quirk resurfacing here.
        menu_kwargs = {"bg": THEME["surface"], "fg": THEME["ink"],
                        "activebackground": THEME["accent"], "activeforeground": THEME["accent_ink"]}
        dev_menu = tk.Menu(self.root, tearoff=0, **menu_kwargs)
        dev_menu.add_command(label=t("menu_rsz_snapshot"), command=self._open_snapshot_dialog)
        settings_menu = tk.Menu(self.root, tearoff=0, **menu_kwargs)
        settings_menu.add_cascade(label=t("menu_dev_options"), menu=dev_menu)
        self.btn_settings.configure(menu=settings_menu)
        self._settings_menu, self._dev_menu = settings_menu, dev_menu

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill="x", **pad)
        self.btn_settings = ttk.Menubutton(top_frame, text=t("menu_settings"))
        self.btn_settings.pack(side="left")
        self._build_menubar()
        # "적용 방어구 변경" entry point (opens a separate dialog -- kept out
        # of the main repair flow on purpose; see _open_retarget_dialog).
        self.btn_retarget = ttk.Button(top_frame, text=t("btn_retarget"), command=self._open_retarget_dialog)
        self.btn_retarget.pack(side="left", padx=(8, 0))
        self.lbl_retarget_info = ttk.Label(top_frame, text="ⓘ", foreground=THEME["accent"], cursor="question_arrow")
        self.lbl_retarget_info.pack(side="left", padx=(4, 0))
        _Tooltip(self.lbl_retarget_info, lambda: t("tip_retarget"))
        # "적용 무기 변경" -- weapon-model retargeting, same rationale as the
        # armor button above (separate dialog, kept out of the main repair
        # flow); see _open_weapon_retarget_dialog / weapon_retarget.py.
        self.btn_weapon_retarget = ttk.Button(
            top_frame, text=t("btn_weapon_retarget"), command=self._open_weapon_retarget_dialog)
        self.btn_weapon_retarget.pack(side="left", padx=(8, 0))
        self.lbl_weapon_retarget_info = ttk.Label(
            top_frame, text="ⓘ", foreground=THEME["accent"], cursor="question_arrow")
        self.lbl_weapon_retarget_info.pack(side="left", padx=(4, 0))
        _Tooltip(self.lbl_weapon_retarget_info, lambda: t("tip_weapon_retarget"))
        self.lbl_lang = ttk.Label(top_frame, text=t("lbl_lang"))
        self.lbl_lang.pack(side="right", padx=(6, 0))
        self.lang_combo = ttk.Combobox(
            top_frame, textvariable=self.lang_display, state="readonly",
            values=list(i18n.LANGUAGES.values()), width=10,
        )
        self.lang_combo.pack(side="right")
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_lang_change)

        game_frame = ttk.Frame(self.root)
        game_frame.pack(fill="x", padx=10, pady=(0, 6))
        self.lbl_game_dir = ttk.Label(game_frame, text=t("lbl_game_dir"))
        self.lbl_game_dir.pack(side="left")
        ttk.Entry(game_frame, textvariable=self.game_dir).pack(side="left", fill="x", expand=True, padx=6)
        self.btn_browse_game = ttk.Button(game_frame, text=t("btn_browse_game"), command=self._browse_game_dir)
        self.btn_browse_game.pack(side="left")

        fluffy_frame = ttk.Frame(self.root)
        fluffy_frame.pack(fill="x", padx=10, pady=(0, 6))
        self.lbl_fluffy_dir = ttk.Label(fluffy_frame, text=t("lbl_fluffy_dir"))
        self.lbl_fluffy_dir.pack(side="left")
        ttk.Entry(fluffy_frame, textvariable=self.fluffy_dir).pack(side="left", fill="x", expand=True, padx=6)
        self.btn_browse_fluffy = ttk.Button(fluffy_frame, text=t("btn_browse_game"), command=self._browse_fluffy_dir)
        self.btn_browse_fluffy.pack(side="left")

        list_label_frame = ttk.Frame(self.root)
        list_label_frame.pack(fill="x", padx=10)
        self.lbl_mod_list = ttk.Label(list_label_frame, text=t("lbl_mod_list"))
        self.lbl_mod_list.pack(side="left")

        list_frame = ttk.Frame(self.root)
        list_frame.pack(fill="both", padx=10, pady=4)
        self.mod_listbox = tk.Listbox(
            list_frame, height=6, selectmode="extended",
            bg=THEME["surface"], fg=THEME["ink"],
            selectbackground=THEME["accent"], selectforeground=THEME["accent_ink"],
            highlightthickness=1, highlightbackground=THEME["border"], highlightcolor=THEME["border"],
            relief="flat", borderwidth=0,
        )
        self.mod_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, command=self.mod_listbox.yview)
        scrollbar.pack(side="left", fill="y")
        self.mod_listbox.configure(yscrollcommand=scrollbar.set)

        if _HAS_DND:
            self.mod_listbox.drop_target_register(DND_FILES)
            self.mod_listbox.dnd_bind("<<Drop>>", self._on_drop)
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=10, pady=(0, 6))
        self.btn_add_mod = ttk.Button(btn_frame, text=t("btn_add_mod"), command=self._browse_mod)
        self.btn_add_mod.pack(side="left")
        self.btn_remove_selected = ttk.Button(btn_frame, text=t("btn_remove_selected"), command=self._remove_selected)
        self.btn_remove_selected.pack(side="left", padx=6)
        self.btn_clear_all = ttk.Button(btn_frame, text=t("btn_clear_all"), command=self._clear_queue)
        self.btn_clear_all.pack(side="left")

        self.options_frame = ttk.LabelFrame(self.root, text=t("lbl_experimental_options"))
        self.options_frame.pack(fill="x", padx=10, pady=(4, 6))
        row_frame = ttk.Frame(self.options_frame)
        row_frame.pack(fill="x", padx=8, pady=(4, 0))
        self.chk_force_unresolved = ttk.Checkbutton(
            row_frame, text=t("chk_force_unresolved"), variable=self.force_unresolved,
        )
        self.chk_force_unresolved.pack(side="left")
        _Tooltip(self.chk_force_unresolved, lambda: t("tip_force_unresolved"))
        self.chk_preserve_extra = ttk.Checkbutton(
            row_frame, text=t("chk_preserve_extra"), variable=self.preserve_extra,
        )
        self.chk_preserve_extra.pack(side="left", padx=(14, 0))
        _Tooltip(self.chk_preserve_extra, lambda: t("tip_preserve_extra"))
        self.chk_shader_migration = ttk.Checkbutton(
            row_frame, text=t("chk_shader_migration"), variable=self.shader_migration,
        )
        self.chk_shader_migration.pack(side="left", padx=(14, 0))
        _Tooltip(self.chk_shader_migration, lambda: t("tip_shader_migration"))
        self.lbl_experimental_hint = ttk.Label(
            self.options_frame, text=t("lbl_experimental_hint"), foreground=THEME["warn"], font=("Segoe UI", 8),
        )
        self.lbl_experimental_hint.pack(anchor="w", padx=8, pady=(4, 6))

        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", **pad)
        # Plain tk.Button, not ttk -- ttk buttons ignore bg/fg color overrides
        # under most themes (including 'clam', set in _apply_theme()), so
        # this is the only reliable way to make the primary action stand out
        # with the accent color rather than the same neutral button color as
        # everything else on this screen.
        self.start_btn = tk.Button(
            action_frame, text=t("btn_start"), command=self._start,
            bg=THEME["accent"], fg=THEME["accent_ink"],
            activebackground=THEME["accent_hover"], activeforeground=THEME["accent_ink"],
            disabledforeground=THEME["muted"], relief="flat", font=("Segoe UI", 10, "bold"),
            padx=16, pady=6, cursor="hand2",
        )
        self.start_btn.pack(side="left")
        self.btn_open_log = ttk.Button(action_frame, text=t("btn_open_log_folder"), command=self._open_log_folder)
        self.btn_open_log.pack(side="left", padx=6)

        ttk.Label(self.root, textvariable=self.status).pack(fill="x", padx=10)

        self.notice_verifying = StringVar(value="")
        self.lbl_notice = ttk.Label(self.root, textvariable=self.notice_verifying, foreground=THEME["warn"])
        self.lbl_notice.pack(fill="x", padx=10)

        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill="x", padx=10, pady=(0, 4))
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True)
        self.progress_pct_label = ttk.Label(progress_frame, text="", width=6, anchor="e")
        self.progress_pct_label.pack(side="left", padx=(6, 0))

        self.log_text = ScrolledText(
            self.root, height=16, state="disabled",
            bg=THEME["log_bg"], fg=THEME["ink"], insertbackground=THEME["ink"],
            relief="flat", borderwidth=1, highlightthickness=1,
            highlightbackground=THEME["border"], highlightcolor=THEME["border"],
            font=("Consolas", 9),
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)
        # Color-coded by the same [fixed]/[warn]/[error]/[info] markers this
        # project's own log() callers already use everywhere (pfb_fix.py,
        # auto_fix.py, etc.) -- see _log_tag_for(). Purely cosmetic: never
        # changes what gets logged, only how it's colored once inserted.
        self.log_text.tag_configure("logok", foreground=THEME["success"])
        self.log_text.tag_configure("logwarn", foreground=THEME["warn"])
        self.log_text.tag_configure("logerror", foreground=THEME["danger"])
        self.log_text.tag_configure("logdim", foreground=THEME["muted"])

    def _on_lang_change(self, event=None):
        code = next((c for c, name in i18n.LANGUAGES.items() if name == self.lang_display.get()), "en")
        i18n.set_language(code)
        i18n.save_language(code)
        self._retranslate()

    def _retranslate(self):
        self.btn_settings.configure(text=t("menu_settings"))
        self._build_menubar()
        self.btn_retarget.configure(text=t("btn_retarget"))
        self.btn_weapon_retarget.configure(text=t("btn_weapon_retarget"))
        self.lbl_lang.configure(text=t("lbl_lang"))
        self.lbl_game_dir.configure(text=t("lbl_game_dir"))
        self.btn_browse_game.configure(text=t("btn_browse_game"))
        self.lbl_fluffy_dir.configure(text=t("lbl_fluffy_dir"))
        self.btn_browse_fluffy.configure(text=t("btn_browse_game"))
        self.lbl_mod_list.configure(text=t("lbl_mod_list"))
        self.btn_add_mod.configure(text=t("btn_add_mod"))
        self.btn_remove_selected.configure(text=t("btn_remove_selected"))
        self.btn_clear_all.configure(text=t("btn_clear_all"))
        self.options_frame.configure(text=t("lbl_experimental_options"))
        self.chk_force_unresolved.configure(text=t("chk_force_unresolved"))
        self.chk_preserve_extra.configure(text=t("chk_preserve_extra"))
        self.chk_shader_migration.configure(text=t("chk_shader_migration"))
        self.lbl_experimental_hint.configure(text=t("lbl_experimental_hint"))
        self.start_btn.configure(text=t("btn_start"))
        self.btn_open_log.configure(text=t("btn_open_log_folder"))
        if self._busy:
            self.notice_verifying.set(t("notice_verifying"))
        else:
            self.status.set(t("status_default"))
        if self._retarget_refresh_fn is not None:
            self._retarget_refresh_fn()
        if self._weapon_retarget_refresh_fn is not None:
            self._weapon_retarget_refresh_fn()
        if self._snapshot_refresh_fn is not None:
            self._snapshot_refresh_fn()

    def _open_log_folder(self):
        try:
            os.startfile(LOG_DIR)
        except OSError:
            pass

    def _open_snapshot_dialog(self):
        """Settings > Developer Options > RSZ Snapshot -- shows what's
        currently installed (see rsz_layout.list_snapshots()) and lets a
        user install a snapshot someone shared, without waiting for a new
        MHWmodfixer release. See rsz_layout.py's module docstring for what
        this snapshot actually protects."""
        win = tk.Toplevel(self.root, bg=THEME["bg"])
        win.title(t("dlg_snapshot_title"))
        win.geometry("560x380")
        win.transient(self.root)

        info_text = ScrolledText(
            win, height=14, state="disabled",
            bg=THEME["log_bg"], fg=THEME["ink"], insertbackground=THEME["ink"],
            relief="flat", borderwidth=1, highlightthickness=1,
            highlightbackground=THEME["border"], highlightcolor=THEME["border"],
            font=("Consolas", 9),
        )
        info_text.pack(fill="both", expand=True, padx=10, pady=10)

        def refresh():
            lines = []
            for entry in rsz_layout.list_snapshots():
                role = t("snap_role_current") if entry["role"] == "current" else t("snap_role_archived")
                lines.append(f"[{role}] {entry['path'].name}")
                if not entry["exists"]:
                    lines.append(f"  {t('snap_not_present')}")
                else:
                    meta = entry["meta"] or {}
                    lines.append(f"  {t('snap_label')}: {meta.get('label', '?')}")
                    lines.append(f"  {t('snap_game_date')}: {meta.get('game_update_date', '?')}")
                    lines.append(f"  {t('snap_baked_at')}: {meta.get('baked_at', '?')}")
                    lines.append(f"  {t('snap_type_count')}: {meta.get('entry_count', '?')}")
                lines.append("")
            info_text.configure(state="normal")
            info_text.delete("1.0", "end")
            info_text.insert("1.0", "\n".join(lines))
            info_text.configure(state="disabled")

        refresh()

        progress_frame = ttk.Frame(win)
        progress_frame.pack(fill="x", padx=10, pady=(0, 4))
        dlg_progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        dlg_progress.pack(side="left", fill="x", expand=True)
        dlg_progress_label = ttk.Label(progress_frame, text="", width=10, anchor="e")
        dlg_progress_label.pack(side="left", padx=(6, 0))

        def _set_busy(busy: bool):
            state = "disabled" if busy else "normal"
            btn_import.configure(state=state)
            btn_check.configure(state=state)
            if not busy:
                dlg_progress.configure(value=0)
                dlg_progress_label.configure(text="")

        def _report_install(meta: dict, verify_result: bool | None):
            suffix = (t("msg_snapshot_verify_ok") if verify_result is True else
                      t("msg_snapshot_verify_fail") if verify_result is False else
                      t("msg_snapshot_verify_unknown"))
            merge_stats = meta.get("merge_stats")
            if merge_stats:
                suffix += t("msg_snapshot_merge_stats", **merge_stats)
            messagebox.showinfo(
                APP_TITLE, t("msg_snapshot_installed", count=meta["entry_count"], label=meta["label"]) + suffix,
                parent=win)
            _set_busy(False)
            refresh()

        def do_import():
            path = filedialog.askopenfilename(
                title=t("dlg_choose_snapshot"),
                filetypes=[(t("filetype_snapshot"), ("*.json.gz", "*.json")), (t("filetype_allfiles"), "*.*")],
            )
            if not path:
                return
            role_yes = messagebox.askyesnocancel(APP_TITLE, t("ask_snapshot_role"), parent=win)
            if role_yes is None:
                return
            role = "current" if role_yes else "archive"
            try:
                meta = rsz_layout.install_snapshot(Path(path), as_role=role)
            except rsz_layout.SnapshotError as exc:
                messagebox.showerror(APP_TITLE, t("err_snapshot_import", e=exc), parent=win)
                return
            except Exception as exc:
                messagebox.showerror(APP_TITLE, t("err_unhandled", e=exc), parent=win)
                return
            verify_result = None
            if role == "current" and Path(self.game_dir.get()).is_dir():
                game = GameArchive(self.game_dir.get(), log=lambda *a, **k: None)
                verify_result = rsz_layout.verify_against_live_game(game)
            _report_install(meta, verify_result)

        def do_check_github():
            if not messagebox.askyesno(APP_TITLE, t("ask_confirm_download"), parent=win):
                return
            _set_busy(True)

            def update_progress(done, total):
                pct = round(done / total * 100) if total > 0 else 0
                label = f"{pct}%" if total > 0 else f"{done // 1_000_000}MB"
                win.after(0, lambda: (dlg_progress.configure(value=pct), dlg_progress_label.configure(text=label)))

            def worker():
                try:
                    dump_path = rsz_layout.fetch_latest_dump(progress_cb=update_progress)
                    meta = rsz_layout.install_snapshot(dump_path, as_role="current")
                    verify_result = None
                    if Path(self.game_dir.get()).is_dir():
                        game = GameArchive(self.game_dir.get(), log=lambda *a, **k: None)
                        verify_result = rsz_layout.verify_against_live_game(game)
                except Exception as exc:
                    # t()/format the message NOW -- `exc` is unbound the
                    # instant this except block exits, so a lambda that
                    # only captures the name (not its value) would raise
                    # NameError when win.after() finally invokes it later.
                    err_text = t("err_download_failed", e=exc)
                    win.after(0, lambda: (messagebox.showerror(APP_TITLE, err_text, parent=win),
                                          _set_busy(False)))
                    return
                win.after(0, lambda: _report_install(meta, verify_result))

            threading.Thread(target=worker, daemon=True).start()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        btn_import = ttk.Button(btn_frame, text=t("btn_import_snapshot"), command=do_import)
        btn_import.pack(side="left")
        btn_check = ttk.Button(btn_frame, text=t("btn_check_github"), command=do_check_github)
        btn_check.pack(side="left", padx=(6, 0))
        btn_close = ttk.Button(btn_frame, text=t("btn_close"))
        btn_close.pack(side="right")

        def on_close():
            self._snapshot_refresh_fn = None
            win.destroy()

        btn_close.configure(command=on_close)
        win.protocol("WM_DELETE_WINDOW", on_close)

        def refresh_texts():
            """Same pattern as _open_retarget_dialog()'s own refresh hook
            -- this dialog's widgets are all built once, outside
            _retranslate()'s reach, so without this a language switch
            while the dialog is open left it frozen in the old language
            (confirmed directly by the user, same symptom as the
            retarget dialog before that fix)."""
            win.title(t("dlg_snapshot_title"))
            btn_import.configure(text=t("btn_import_snapshot"))
            btn_check.configure(text=t("btn_check_github"))
            btn_close.configure(text=t("btn_close"))
            refresh()  # already re-renders info_text's body via fresh t() calls

        self._snapshot_refresh_fn = refresh_texts

    def _open_retarget_dialog(self):
        """'적용 방어구 변경' -- relocate a mod built for one or more ch03/
        ch02 armor slots onto different, physics-compatible slots (see
        slot_retarget.py and CLAUDE.md #33/#34 for the verified recipe).
        Deliberately a separate Toplevel, not a tab next to the repair flow
        -- the two features have unrelated workflows (batch-repair-many vs
        pick-one-and-choose-a-target) and the user asked for them to stay
        visually distinct.

        A mod can legitimately touch SEVERAL different slots at once
        (confirmed real cases: DOTEI's EULA stashes custom textures under
        4 unrelated slots' folders; TiNE's Qipao ships two full slots'
        worth of piece files in one FOMOD page) -- rather than refusing or
        silently leaving the extras behind, every detected slot gets its
        own row and its own explicit decision (move it somewhere, or leave
        it exactly where it is), and generation is blocked until every
        single one has been decided."""
        import slot_retarget
        import fluffy_installed

        win = tk.Toplevel(self.root, bg=THEME["bg"])
        win.title(t("dlg_retarget_title"))
        win.geometry("680x640")
        win.minsize(600, 480)
        win.transient(self.root)

        file_frame = ttk.Frame(win)
        file_frame.pack(fill="x", padx=10, pady=10)
        file_label = ttk.Label(file_frame, text=t("lbl_retarget_file"))
        file_label.pack(side="left")
        file_var = StringVar(value="")
        ttk.Entry(file_frame, textvariable=file_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=6)
        btn_pick = ttk.Button(file_frame, text=t("btn_choose_file"))
        btn_pick.pack(side="left")

        info_label = ttk.Label(win, text=t("msg_retarget_no_file"), justify="left", wraplength=640)
        info_label.pack(anchor="w", padx=10, pady=(0, 8))

        slots_frame = ttk.LabelFrame(win, text=t("lbl_retarget_slots"))
        slots_frame.pack(fill="both", expand=False, padx=10, pady=(0, 8))
        slot_columns = ("slot", "name", "gender", "files", "status")
        slot_tree = ttk.Treeview(slots_frame, columns=slot_columns, show="headings",
                                  height=5, selectmode="browse")
        for col, key, width in [("slot", "col_slot", 80), ("name", "col_armor", 100),
                                 ("gender", "col_gender", 55), ("files", "col_files", 55),
                                 ("status", "col_status", 220)]:
            slot_tree.heading(col, text=t(key))
            slot_tree.column(col, width=width, anchor="w")
        slot_vsb = ttk.Scrollbar(slots_frame, orient="vertical", command=slot_tree.yview)
        slot_tree.configure(yscrollcommand=slot_vsb.set)
        slot_tree.pack(side="left", fill="both", expand=True)
        slot_vsb.pack(side="right", fill="y")
        slot_tree.tag_configure("done", foreground=THEME["success"])
        slot_tree.tag_configure("pending", foreground=THEME["warn"])

        # Confirmed real 2026-08-14 (DOA "Ninja 2015- Ayane" -> a real
        # target-dependent wrist-accessory failure): a piece NUMBERED beyond
        # the standard 5 (Arm/Body/Helm/Leg/Waist) -- e.g. a bonus mesh-only
        # accessory some mods ship as piece 6 -- gets relocated by plain
        # part-level renaming like everything else, but `armor_slots_ch03
        # .json.gz`'s own compatibility data (see bake_armor_slots.py) only
        # ever tracks pieces 1-5. There's no way for this tool to verify the
        # CHOSEN target's real vanilla structure has an equivalent slot for
        # it -- confirmed empirically: the same mod's piece 6 rendered fine
        # retargeted to one slot and vanished retargeted to another, with
        # zero warning either way. Shown per-slot (not per-candidate, since
        # it's a property of the SOURCE mod, true regardless of which target
        # gets picked), right under the slot list.
        extra_pieces_label = ttk.Label(win, text="", justify="left", wraplength=640, foreground=THEME["warn"])
        extra_pieces_label.pack(anchor="w", padx=10, pady=(0, 8))

        def _extra_pieces_text(group) -> str:
            extra = sorted(p for p in group.pieces_shipped if p > 5)
            if not extra:
                return ""
            return t("note_extra_pieces_unverified", pieces=", ".join(map(str, extra)))

        cand_frame = ttk.LabelFrame(win, text=t("lbl_retarget_targets"))
        cand_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        cand_columns = ("slot", "name", "gender", "grade", "note")
        cand_tree = ttk.Treeview(cand_frame, columns=cand_columns, show="headings",
                                  height=8, selectmode="browse")
        for col, key, width in [("slot", "col_slot", 80), ("name", "col_armor", 100),
                                 ("gender", "col_gender", 55), ("grade", "col_compat", 100),
                                 ("note", "col_note", 220)]:
            cand_tree.heading(col, text=t(key))
            cand_tree.column(col, width=width, anchor="w")
        cand_vsb = ttk.Scrollbar(cand_frame, orient="vertical", command=cand_tree.yview)
        cand_tree.configure(yscrollcommand=cand_vsb.set)
        cand_tree.pack(side="left", fill="both", expand=True)
        cand_vsb.pack(side="right", fill="y")
        cand_tree.tag_configure("exact", foreground=THEME["success"])
        cand_tree.tag_configure("partial", foreground=THEME["warn"])
        cand_tree.tag_configure("gpuc", foreground=THEME["danger"])

        cand_btn_frame = ttk.Frame(win)
        cand_btn_frame.pack(fill="x", padx=10, pady=(0, 8))
        btn_apply = ttk.Button(cand_btn_frame, text=t("btn_apply_to_slot"), state="disabled")
        btn_apply.pack(side="left")
        btn_leave = ttk.Button(cand_btn_frame, text=t("btn_leave_unchanged"), state="disabled")
        btn_leave.pack(side="left", padx=(6, 0))

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", padx=10, pady=10)
        status_var = StringVar(value="")
        ttk.Label(btn_frame, textvariable=status_var, foreground=THEME["muted"]).pack(side="left")
        btn_generate = ttk.Button(btn_frame, text=t("btn_generate_retarget"), state="disabled")
        btn_generate.pack(side="right")
        btn_close = ttk.Button(btn_frame, text=t("btn_close"))
        btn_close.pack(side="right", padx=(0, 6))

        def on_close():
            self._retarget_refresh_fn = None
            win.destroy()

        btn_close.configure(command=on_close)
        win.protocol("WM_DELETE_WINDOW", on_close)

        state = {"groups": [], "unmatched": [], "assignments": {}, "active_key": None,
                 "candidates_by_key": {}, "occupancy_by_key": {}, "fluffy_index": {}}
        table = slot_retarget.slot_table()

        def set_pick_busy(busy: bool):
            btn_pick.configure(state="disabled" if busy else "normal")

        def _refresh_generate_enabled():
            groups = state["groups"]
            ready = bool(groups) and all(g.key in state["assignments"] for g in groups)
            btn_generate.configure(state="normal" if ready else "disabled")

        def _status_text_for(key):
            lang = i18n.get_language()
            if key not in state["assignments"]:
                return t("status_pending"), "pending"
            dst = state["assignments"][key]
            if dst is None:
                return t("status_unchanged"), "done"
            dst_key = f"{dst[0]}/{dst[1]}"
            dst_entry = table.get(dst_key, {})
            dst_name = slot_retarget.armor_name(dst_entry.get("name", "?"), dst_entry.get("names", {}), lang)
            return t("status_target", name=dst_name, slot=dst_key), "done"

        def _refresh_slot_row(key):
            text, tag = _status_text_for(key)
            vals = list(slot_tree.item(key, "values"))
            vals[4] = text
            slot_tree.item(key, values=vals, tags=(tag,))

        def start_pick(path):
            if not path:
                return
            file_var.set(path)
            slot_tree.delete(*slot_tree.get_children())
            cand_tree.delete(*cand_tree.get_children())
            extra_pieces_label.configure(text="")
            state["groups"], state["unmatched"], state["assignments"], state["active_key"] = [], [], {}, None
            state["archive_password"] = None
            info_label.configure(text=t("msg_retarget_detecting"))
            btn_apply.configure(state="disabled")
            btn_leave.configure(state="disabled")
            btn_generate.configure(state="disabled")
            set_pick_busy(True)

            def worker():
                try:
                    import tempfile
                    work = Path(tempfile.mkdtemp(prefix="retarget_ui_"))
                    try:
                        mod_root, state["archive_password"] = self.extract_archive_prompting(Path(path), work)
                        groups, unmatched = slot_retarget.detect_mod_slots(mod_root)
                    finally:
                        shutil.rmtree(work, ignore_errors=True)
                except Exception as exc:
                    err_text = t("err_unhandled", e=exc)  # format now -- exc unbinds when this block exits
                    win.after(0, lambda: (info_label.configure(text=err_text), set_pick_busy(False)))
                    return
                win.after(0, lambda: _on_detected(groups, unmatched))

            threading.Thread(target=worker, daemon=True).start()

        def do_pick():
            path = filedialog.askopenfilename(
                title=t("dlg_choose_mod_archive"),
                filetypes=[(t("filetype_mod_archive"), ("*.zip", "*.7z", "*.rar")),
                           (t("filetype_allfiles"), "*.*")],
            )
            start_pick(path)

        def on_drop(event):
            for raw in win.tk.splitlist(event.data):
                p = Path(raw)
                if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS:
                    start_pick(str(p))
                    return

        if _HAS_DND:
            win.drop_target_register(DND_FILES)
            win.dnd_bind("<<Drop>>", on_drop)

        def _on_detected(groups, unmatched):
            set_pick_busy(False)
            state["groups"], state["unmatched"] = groups, unmatched
            state["fluffy_index"] = self._load_fluffy_index()
            if not groups:
                info_label.configure(text=t("msg_retarget_no_slot_found"))
                return
            info_label.configure(text=t("msg_retarget_multi_summary", count=len(groups), unmatched=len(unmatched)))
            lang = i18n.get_language()
            for g in groups:
                gl = slot_retarget.gender_label(g.gender, lang)
                gname = slot_retarget.armor_name(g.name, g.names, lang)
                slot_tree.insert("", "end", iid=g.key,
                                  values=(g.key, gname, gl, len(g.files), t("status_pending")),
                                  tags=("pending",))
            slot_tree.selection_set(groups[0].key)
            _select_slot(groups[0].key)

        def _select_slot(key):
            state["active_key"] = key
            group = next(g for g in state["groups"] if g.key == key)
            extra_pieces_label.configure(text=_extra_pieces_text(group))
            cand_tree.delete(*cand_tree.get_children())
            if key in state["candidates_by_key"]:
                cands = state["candidates_by_key"][key]
            else:
                cands = slot_retarget.find_compatible_targets(group)
                state["candidates_by_key"][key] = cands
            lang = i18n.get_language()
            grade_text = {"exact": t("grade_exact"), "partial": t("grade_partial"), "gpuc": t("grade_gpuc")}
            game_dir = self.game_dir.get()
            occ_by_cand = state["occupancy_by_key"].setdefault(key, {})
            for c in cands:
                note = ""
                if c.lost_pieces:
                    note = t("note_lost_physics", pieces=",".join(map(str, c.lost_pieces)))
                elif c.gpuc_pieces:
                    note = t("note_gpuc_pieces", pieces=",".join(map(str, c.gpuc_pieces)))
                if game_dir and c.key not in occ_by_cand:
                    occ_by_cand[c.key] = slot_retarget.find_target_occupants(game_dir, group, c)
                occ_note = self._occupied_note(state["fluffy_index"], occ_by_cand.get(c.key, []))
                note = f"{note} {occ_note}".strip() if note else occ_note
                gl = slot_retarget.gender_label(c.gender, lang)
                cname = slot_retarget.armor_name(c.name, c.names, lang)
                cand_tree.insert("", "end", iid=c.key, values=(c.key, cname, gl, grade_text[c.grade], note),
                                  tags=(c.grade,))
            btn_apply.configure(state="normal" if cands else "disabled")
            btn_leave.configure(state="normal")
            existing = state["assignments"].get(key)
            if existing is not None and f"{existing[0]}/{existing[1]}" in cand_tree.get_children():
                cand_tree.selection_set(f"{existing[0]}/{existing[1]}")

        def on_slot_selected(_event=None):
            sel = slot_tree.selection()
            if sel:
                _select_slot(sel[0])

        def do_apply_to_slot():
            key = state["active_key"]
            sel = cand_tree.selection()
            if key is None or not sel:
                messagebox.showinfo(APP_TITLE, t("msg_retarget_select_target"), parent=win)
                return
            cand = next(c for c in state["candidates_by_key"][key] if c.key == sel[0])
            state["assignments"][key] = (cand.set_no, cand.variant)
            _refresh_slot_row(key)
            _refresh_generate_enabled()

        def do_leave_unchanged():
            key = state["active_key"]
            if key is None:
                messagebox.showinfo(APP_TITLE, t("msg_retarget_pick_slot_first"), parent=win)
                return
            state["assignments"][key] = None
            _refresh_slot_row(key)
            _refresh_generate_enabled()

        def do_generate():
            groups = state["groups"]
            assignments = state["assignments"]
            if not groups or not all(g.key in assignments for g in groups):
                messagebox.showinfo(APP_TITLE, t("msg_retarget_incomplete"), parent=win)
                return
            if not Path(self.game_dir.get()).is_dir():
                messagebox.showerror(APP_TITLE, t("err_no_game_dir"), parent=win)
                return
            game = GameArchive(self.game_dir.get(), log=lambda *a, **k: None)
            unverified = []
            occupant_relpaths_all = []
            for g in groups:
                dst = assignments[g.key]
                if dst is None:
                    continue
                dst_key = f"{dst[0]}/{dst[1]}"
                cand = next((c for c in state["candidates_by_key"].get(g.key, []) if c.key == dst_key), None)
                if cand is None:
                    cand = slot_retarget.TargetCandidate(key=dst_key, set_no=dst[0], variant=dst[1],
                                                          name=table.get(dst_key, {}).get("name", "?"),
                                                          grade="exact")
                ok, missing = slot_retarget.verify_target_vanilla(game, g, cand)
                if not ok:
                    unverified.append(f"{g.key} -> {dst_key}: {', '.join(missing)}")
                occupant_relpaths_all.extend(
                    state["occupancy_by_key"].get(g.key, {}).get(dst_key)
                    or slot_retarget.find_target_occupants(self.game_dir.get(), g, cand))
            if unverified and not messagebox.askyesno(
                    APP_TITLE, t("ask_retarget_unverified", missing="\n".join(unverified)), parent=win):
                return
            if occupant_relpaths_all and not self._confirm_occupied(
                    state["fluffy_index"], occupant_relpaths_all, win):
                return
            src_stem = Path(file_var.get()).stem
            out_path = filedialog.asksaveasfilename(
                title=t("dlg_save_retarget"), defaultextension=".zip",
                initialfile=f"{src_stem} (retargeted).zip",
                filetypes=[(t("filetype_zip"), "*.zip")],
            )
            if not out_path:
                return
            btn_generate.configure(state="disabled")
            btn_pick.configure(state="disabled")
            status_var.set(t("msg_retarget_generating"))

            def worker():
                try:
                    _, moved_counts = slot_retarget.retarget_archive_multi(
                        Path(file_var.get()), Path(out_path), assignments, log=lambda s: None,
                        password=state.get("archive_password"))
                except Exception as exc:
                    err_text = t("err_unhandled", e=exc)  # format now -- exc unbinds when this block exits
                    win.after(0, lambda: (messagebox.showerror(APP_TITLE, err_text, parent=win),
                                          status_var.set(""), _refresh_generate_enabled(),
                                          btn_pick.configure(state="normal")))
                    return
                moved_total = sum(1 for v in moved_counts.values() if v)
                win.after(0, lambda: (status_var.set(""), _refresh_generate_enabled(),
                                      btn_pick.configure(state="normal"),
                                      messagebox.showinfo(APP_TITLE, t(
                                          "msg_retarget_done", path=out_path,
                                          moved=moved_total, kept=len(moved_counts) - moved_total),
                                          parent=win)))

            threading.Thread(target=worker, daemon=True).start()

        btn_pick.configure(command=do_pick)
        btn_apply.configure(command=do_apply_to_slot)
        btn_leave.configure(command=do_leave_unchanged)
        btn_generate.configure(command=do_generate)
        slot_tree.bind("<<TreeviewSelect>>", on_slot_selected)

        def refresh_texts():
            """Called from App._retranslate() when the main window's
            language selector changes WHILE this dialog is still open --
            without this, every label/column/row here stayed frozen in
            whatever language was active at the moment the dialog opened
            (confirmed directly: switching the main window to Traditional
            Chinese mid-session left this dialog's headers and rows in
            English until closed and reopened)."""
            win.title(t("dlg_retarget_title"))
            file_label.configure(text=t("lbl_retarget_file"))
            btn_pick.configure(text=t("btn_choose_file"))
            slots_frame.configure(text=t("lbl_retarget_slots"))
            cand_frame.configure(text=t("lbl_retarget_targets"))
            for col, key in [("slot", "col_slot"), ("name", "col_armor"), ("gender", "col_gender"),
                              ("files", "col_files"), ("status", "col_status")]:
                slot_tree.heading(col, text=t(key))
            for col, key in [("slot", "col_slot"), ("name", "col_armor"), ("gender", "col_gender"),
                              ("grade", "col_compat"), ("note", "col_note")]:
                cand_tree.heading(col, text=t(key))
            btn_apply.configure(text=t("btn_apply_to_slot"))
            btn_leave.configure(text=t("btn_leave_unchanged"))
            btn_generate.configure(text=t("btn_generate_retarget"))
            btn_close.configure(text=t("btn_close"))

            lang = i18n.get_language()
            if state["groups"]:
                info_label.configure(text=t("msg_retarget_multi_summary",
                                             count=len(state["groups"]), unmatched=len(state["unmatched"])))
            elif not file_var.get():
                info_label.configure(text=t("msg_retarget_no_file"))
            # else: a transient/error message is showing -- left as-is, it
            # self-corrects on the next pick/detect rather than guessing
            # which specific message was live when the language changed.

            for g in state["groups"]:
                gl = slot_retarget.gender_label(g.gender, lang)
                gname = slot_retarget.armor_name(g.name, g.names, lang)
                status_text, tag = _status_text_for(g.key)
                slot_tree.item(g.key, values=(g.key, gname, gl, len(g.files), status_text), tags=(tag,))

            active = state["active_key"]
            active_group = next((g for g in state["groups"] if g.key == active), None) if active else None
            extra_pieces_label.configure(text=_extra_pieces_text(active_group) if active_group else "")
            if active and active in state["candidates_by_key"]:
                grade_text = {"exact": t("grade_exact"), "partial": t("grade_partial"), "gpuc": t("grade_gpuc")}
                occ_by_cand = state["occupancy_by_key"].get(active, {})
                for c in state["candidates_by_key"][active]:
                    note = ""
                    if c.lost_pieces:
                        note = t("note_lost_physics", pieces=",".join(map(str, c.lost_pieces)))
                    elif c.gpuc_pieces:
                        note = t("note_gpuc_pieces", pieces=",".join(map(str, c.gpuc_pieces)))
                    occ_note = self._occupied_note(state["fluffy_index"], occ_by_cand.get(c.key, []))
                    note = f"{note} {occ_note}".strip() if note else occ_note
                    gl = slot_retarget.gender_label(c.gender, lang)
                    cname = slot_retarget.armor_name(c.name, c.names, lang)
                    cand_tree.item(c.key, values=(c.key, cname, gl, grade_text[c.grade], note), tags=(c.grade,))

        self._retarget_refresh_fn = refresh_texts

    def _open_weapon_retarget_dialog(self):
        """'적용 무기 변경' -- relocate a mod built for one or more weapon
        models onto different, physics-compatible models of the SAME
        weapon type (see weapon_retarget.py). Mirrors _open_retarget_dialog
        (armor)'s exact multi-slot architecture: a mod CAN legitimately
        bundle more than one weapon model's files at once (confirmed real
        2026-08-10, "ReyDau_Fixed.zip" -- two distinct (type,sid,iid)
        triples in one flat loose-file tree), so every detected weapon
        gets its own row and its own explicit decision (move it somewhere,
        or leave it exactly where it is), and generation is blocked until
        every single one has been decided -- same reasoning as armor's own
        dialog, ported here 2026-08-10 after the single-target-only
        version turned out to reject a real mod outright."""
        import weapon_retarget
        import fluffy_installed
        import mod_pages

        win = tk.Toplevel(self.root, bg=THEME["bg"])
        win.title(t("dlg_weapon_retarget_title"))
        win.geometry("680x640")
        win.minsize(600, 480)
        win.transient(self.root)

        file_frame = ttk.Frame(win)
        file_frame.pack(fill="x", padx=10, pady=10)
        file_label = ttk.Label(file_frame, text=t("lbl_retarget_file"))
        file_label.pack(side="left")
        file_var = StringVar(value="")
        ttk.Entry(file_frame, textvariable=file_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=6)
        btn_pick = ttk.Button(file_frame, text=t("btn_choose_file"))
        btn_pick.pack(side="left")

        info_label = ttk.Label(win, text=t("msg_weapon_retarget_no_file"), justify="left", wraplength=640)
        info_label.pack(anchor="w", padx=10, pady=(0, 8))

        slots_frame = ttk.LabelFrame(win, text=t("lbl_weapon_retarget_slots"))
        slots_frame.pack(fill="both", expand=False, padx=10, pady=(0, 8))
        slot_columns = ("weapon", "files", "status")
        slot_tree = ttk.Treeview(slots_frame, columns=slot_columns, show="headings",
                                  height=5, selectmode="browse")
        for col, key, width in [("weapon", "col_weapon", 140), ("files", "col_files", 60),
                                 ("status", "col_status", 260)]:
            slot_tree.heading(col, text=t(key))
            slot_tree.column(col, width=width, anchor="w")
        slot_vsb = ttk.Scrollbar(slots_frame, orient="vertical", command=slot_tree.yview)
        slot_tree.configure(yscrollcommand=slot_vsb.set)
        slot_tree.pack(side="left", fill="both", expand=True)
        slot_vsb.pack(side="right", fill="y")
        slot_tree.tag_configure("done", foreground=THEME["success"])
        slot_tree.tag_configure("pending", foreground=THEME["warn"])

        cand_frame = ttk.LabelFrame(win, text=t("lbl_weapon_retarget_targets"))
        cand_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        cand_columns = ("weapon", "grade", "note")
        cand_tree = ttk.Treeview(cand_frame, columns=cand_columns, show="headings",
                                  height=8, selectmode="browse")
        for col, key, width in [("weapon", "col_weapon", 140), ("grade", "col_compat", 110),
                                 ("note", "col_note", 280)]:
            cand_tree.heading(col, text=t(key))
            cand_tree.column(col, width=width, anchor="w")
        cand_vsb = ttk.Scrollbar(cand_frame, orient="vertical", command=cand_tree.yview)
        cand_tree.configure(yscrollcommand=cand_vsb.set)
        cand_tree.pack(side="left", fill="both", expand=True)
        cand_vsb.pack(side="right", fill="y")
        cand_tree.tag_configure("exact", foreground=THEME["success"])
        cand_tree.tag_configure("partial", foreground=THEME["warn"])
        cand_tree.tag_configure("refused", foreground=THEME["danger"])

        cand_btn_frame = ttk.Frame(win)
        cand_btn_frame.pack(fill="x", padx=10, pady=(0, 8))
        btn_apply = ttk.Button(cand_btn_frame, text=t("btn_apply_to_slot"), state="disabled")
        btn_apply.pack(side="left")
        btn_leave = ttk.Button(cand_btn_frame, text=t("btn_leave_unchanged"), state="disabled")
        btn_leave.pack(side="left", padx=(6, 0))

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", padx=10, pady=10)
        status_var = StringVar(value="")
        ttk.Label(btn_frame, textvariable=status_var, foreground=THEME["muted"]).pack(side="left")
        btn_generate = ttk.Button(btn_frame, text=t("btn_generate_retarget"), state="disabled")
        btn_generate.pack(side="right")
        btn_close = ttk.Button(btn_frame, text=t("btn_close"))
        btn_close.pack(side="right", padx=(0, 6))

        def on_close():
            self._weapon_retarget_refresh_fn = None
            _clear_temp_dirs()
            win.destroy()

        btn_close.configure(command=on_close)
        win.protocol("WM_DELETE_WINDOW", on_close)

        state = {"groups": [], "unmatched": [], "assignments": {}, "active_key": None,
                 "candidates_by_key": {}, "occupancy_by_key": {}, "fluffy_index": {},
                 "effective_mod_root": None, "_page_stage_dir": None, "_pick_work_dir": None,
                 "_page_name": None, "archive_password": None}

        def _clear_temp_dirs():
            """Drops the raw-extraction workspace (do_pick()'s own `work`
            dir -- kept alive for the whole pick, not deleted right after
            extraction, since a page-selection pick still needs to read
            mod_root's files from it later) and any previously-extracted-
            and-repaired single-page mod root (_extract_and_repair_page()).
            Picking a NEW file, or closing the dialog, must never leave
            either behind for do_generate() to accidentally reuse or for
            disk space to quietly leak."""
            for key in ("_pick_work_dir", "_page_stage_dir"):
                d = state.get(key)
                if d is not None:
                    shutil.rmtree(d, ignore_errors=True)
                state[key] = None
            state["effective_mod_root"] = None
            state["_page_name"] = None

        def _page_has_real_content(page) -> bool:
            """A FOMOD "cover"/readme-only page (screenshot + blurb, no
            actual weapon files) must never be offered as a selectable
            appearance -- checked by content, not by trusting a
            Fluffy-specific "DummyMod" flag some authors may not set."""
            for p in page.files:
                if p.suffix.lower() == ".pak":
                    return True
                try:
                    rel = str(p.relative_to(page.folder)).lower()
                except ValueError:
                    rel = ""
                if "natives" in rel:
                    return True
            return False

        def _show_page_picker(pages):
            """Modal chooser for detect_mod_pages()'s own list -- returns
            the picked mod_pages.ModPage, or None if the user cancelled.
            Blocks the caller via wait_window(), the standard synchronous
            Tkinter modal pattern -- safe to call here since this always
            runs on the main thread (see _handle_extracted())."""
            picker = tk.Toplevel(win, bg=THEME["bg"])
            picker.title(t("dlg_page_picker_title"))
            picker.geometry("520x380")
            picker.transient(win)
            picker.grab_set()

            ttk.Label(picker, text=t("msg_page_picker_intro"), justify="left",
                      wraplength=480).pack(anchor="w", padx=10, pady=10)

            columns = ("name", "desc")
            tree = ttk.Treeview(picker, columns=columns, show="headings", selectmode="browse")
            tree.heading("name", text=t("col_page_name"))
            tree.heading("desc", text=t("col_page_desc"))
            tree.column("name", width=160, anchor="w")
            tree.column("desc", width=320, anchor="w")
            vsb = ttk.Scrollbar(picker, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=vsb.set)
            tree.pack(side="top", fill="both", expand=True, padx=10)
            vsb.pack(side="right", fill="y")
            for i, page in enumerate(pages):
                tree.insert("", "end", iid=str(i), values=(
                    page.display_name, page.info.get("description", "").strip()))

            result = {"page": None}

            btn_row = ttk.Frame(picker)
            btn_row.pack(fill="x", padx=10, pady=10)
            btn_select = ttk.Button(btn_row, text=t("btn_select_page"), state="disabled")
            btn_select.pack(side="right")
            btn_cancel = ttk.Button(btn_row, text=t("btn_cancel"))
            btn_cancel.pack(side="right", padx=(0, 6))

            def on_select_row(_event=None):
                btn_select.configure(state="normal" if tree.selection() else "disabled")

            def on_confirm():
                sel = tree.selection()
                if sel:
                    result["page"] = pages[int(sel[0])]
                picker.destroy()

            def on_cancel():
                picker.destroy()

            tree.bind("<<TreeviewSelect>>", on_select_row)
            tree.bind("<Double-1>", lambda e: on_confirm())
            btn_select.configure(command=on_confirm)
            btn_cancel.configure(command=on_cancel)
            picker.protocol("WM_DELETE_WINDOW", on_cancel)

            picker.wait_window()
            return result["page"]

        def _weapon_note_for(c) -> str:
            parts = []
            if c.missing_physics:
                key = "note_weapon_missing_physics" if c.grade == "refused" else "note_weapon_partial_physics"
                parts.append(t(key, physics=", ".join(c.missing_physics)))
            if c.loses_gimmick:
                parts.append(t("note_weapon_loses_gimmick"))
            return " ".join(parts)

        def set_pick_busy(busy: bool):
            btn_pick.configure(state="disabled" if busy else "normal")

        def _refresh_generate_enabled():
            groups = state["groups"]
            ready = bool(groups) and all(g.key in state["assignments"] for g in groups)
            btn_generate.configure(state="normal" if ready else "disabled")

        def _status_text_for(key):
            lang = i18n.get_language()
            if key not in state["assignments"]:
                return t("status_pending"), "pending"
            dst = state["assignments"][key]
            if dst is None:
                return t("status_unchanged"), "done"
            dst_key = f"it{dst[0]}/{dst[1]}/{dst[2]}"
            return t("status_target", name=weapon_retarget.weapon_label(dst_key, lang), slot=dst_key), "done"

        def _refresh_slot_row(key):
            text, tag = _status_text_for(key)
            vals = list(slot_tree.item(key, "values"))
            vals[2] = text
            slot_tree.item(key, values=vals, tags=(tag,))

        def _run_weapon_detection(mod_root):
            """Runs weapon_retarget.detect_mod_weapons() on `mod_root` in a
            background thread and lands the result in _on_detected() --
            shared by both the plain (no page selection needed) and the
            page-selected (already extracted+repaired) paths below."""
            def worker():
                try:
                    groups, unmatched = weapon_retarget.detect_mod_weapons(mod_root)
                except Exception as exc:
                    err_text = t("err_unhandled", e=exc)  # format now -- exc unbinds when this block exits
                    win.after(0, lambda: (info_label.configure(text=err_text), set_pick_busy(False)))
                    return
                win.after(0, lambda: _on_detected(groups, unmatched))

            threading.Thread(target=worker, daemon=True).start()

        def _extract_and_repair_page(page):
            """Pulls `page` out of the multi-page archive as its own
            standalone mod (mod_pages.extract_page_standalone -- strips
            AddOnFor, ensures NameAsBundle) and runs it through the SAME
            repair pipeline the main window's own repair flow uses
            (process_mod() + repackage_for_fluffy()), mirroring auto_fix.py
            CLI's own copytree-then-patch-in-place sequence. The repaired
            result becomes state["effective_mod_root"] -- do_generate()
            uses it instead of re-extracting the original (whole, still
            multi-page) archive."""
            game_dir = self.game_dir.get()
            if not game_dir or not Path(game_dir).is_dir():
                info_label.configure(text=t("err_no_game_dir"))
                set_pick_busy(False)
                return
            info_label.configure(text=t("msg_weapon_retarget_page_repairing"))

            def worker():
                try:
                    parent = Path(tempfile.mkdtemp(prefix="weapon_retarget_page_"))
                    raw_stage = parent / "raw"
                    fixed_stage = parent / "fixed"
                    mod_pages.extract_page_standalone(page, raw_stage)
                    shutil.copytree(raw_stage, fixed_stage)
                    game = GameArchive(game_dir, log=lambda *a, **k: None)
                    process_mod(raw_stage, fixed_stage, game, allow_cross_piece=True,
                                log=lambda *a, **k: None)
                    repackage_for_fluffy(fixed_stage, log=lambda *a, **k: None)
                    state["_page_stage_dir"] = parent
                    state["effective_mod_root"] = fixed_stage
                    state["_page_name"] = page.display_name
                except Exception as exc:
                    err_text = t("err_unhandled", e=exc)  # format now -- exc unbinds when this block exits
                    win.after(0, lambda: (info_label.configure(text=err_text), set_pick_busy(False)))
                    return
                win.after(0, lambda: _run_weapon_detection(fixed_stage))

            threading.Thread(target=worker, daemon=True).start()

        def _handle_extracted(mod_root, pages):
            """Called on the main thread once the archive is extracted and
            its FOMOD pages (if any) are known. A single-page (or no
            page-folder-structure) mod proceeds exactly as before; a
            multi-page mod (e.g. "Summer Fleet Weapons" bundling several
            unrelated weapon reskins as separate pages, 2026-08-15) shows
            the page picker first, so the user can pull out just the one
            appearance they actually want."""
            if len(pages) <= 1:
                _run_weapon_detection(mod_root)
                return
            chosen = _show_page_picker(pages)
            if chosen is None:
                set_pick_busy(False)
                info_label.configure(text=t("msg_weapon_retarget_no_file"))
                file_var.set("")
                return
            _extract_and_repair_page(chosen)

        def start_pick(path):
            if not path:
                return
            file_var.set(path)
            slot_tree.delete(*slot_tree.get_children())
            cand_tree.delete(*cand_tree.get_children())
            state["groups"], state["unmatched"], state["assignments"], state["active_key"] = [], [], {}, None
            state["archive_password"] = None
            _clear_temp_dirs()
            info_label.configure(text=t("msg_retarget_detecting"))
            btn_apply.configure(state="disabled")
            btn_leave.configure(state="disabled")
            btn_generate.configure(state="disabled")
            set_pick_busy(True)

            def worker():
                try:
                    # NOT cleaned up here, unlike every other one-shot use of
                    # extract_archive_prompting() elsewhere in this file --
                    # mod_root (and therefore `work`) still needs to be read
                    # from later, either by _run_weapon_detection() directly
                    # (single/no-page case) or by _extract_and_repair_page()
                    # copying a chosen page's own files out of it (multi-page
                    # case). Torn down by _clear_temp_dirs() instead, once a
                    # NEW pick starts or the dialog closes.
                    work = Path(tempfile.mkdtemp(prefix="weapon_retarget_ui_"))
                    state["_pick_work_dir"] = work
                    mod_root, state["archive_password"] = self.extract_archive_prompting(Path(path), work)
                    pages = [p for p in mod_pages.detect_mod_pages(mod_root) if _page_has_real_content(p)]
                except Exception as exc:
                    err_text = t("err_unhandled", e=exc)  # format now -- exc unbinds when this block exits
                    win.after(0, lambda: (info_label.configure(text=err_text), set_pick_busy(False)))
                    return
                win.after(0, lambda: _handle_extracted(mod_root, pages))

            threading.Thread(target=worker, daemon=True).start()

        def do_pick():
            path = filedialog.askopenfilename(
                title=t("dlg_choose_mod_archive"),
                filetypes=[(t("filetype_mod_archive"), ("*.zip", "*.7z", "*.rar")),
                           (t("filetype_allfiles"), "*.*")],
            )
            start_pick(path)

        def on_drop(event):
            for raw in win.tk.splitlist(event.data):
                p = Path(raw)
                if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS:
                    start_pick(str(p))
                    return

        if _HAS_DND:
            win.drop_target_register(DND_FILES)
            win.dnd_bind("<<Drop>>", on_drop)

        def _on_detected(groups, unmatched):
            set_pick_busy(False)
            state["groups"], state["unmatched"] = groups, unmatched
            state["fluffy_index"] = self._load_fluffy_index()
            if not groups:
                info_label.configure(text=t("msg_weapon_retarget_no_slot_found"))
                return
            info_label.configure(text=t("msg_weapon_retarget_multi_summary",
                                         count=len(groups), unmatched=len(unmatched)))
            lang = i18n.get_language()
            for g in groups:
                slot_tree.insert("", "end", iid=g.key,
                                  values=(weapon_retarget.weapon_label(g.key, lang), len(g.files), t("status_pending")),
                                  tags=("pending",))
            slot_tree.selection_set(groups[0].key)
            _select_slot(groups[0].key)

        def _select_slot(key):
            state["active_key"] = key
            group = next(g for g in state["groups"] if g.key == key)
            cand_tree.delete(*cand_tree.get_children())
            if key in state["candidates_by_key"]:
                cands = state["candidates_by_key"][key]
            else:
                cands = weapon_retarget.find_compatible_weapon_targets(group)
                state["candidates_by_key"][key] = cands
            lang = i18n.get_language()
            grade_text = {"exact": t("grade_weapon_exact"), "partial": t("grade_weapon_partial"),
                          "refused": t("grade_weapon_refused")}
            game_dir = self.game_dir.get()
            occ_by_cand = state["occupancy_by_key"].setdefault(key, {})
            for c in cands:
                note = _weapon_note_for(c)
                if game_dir and c.key not in occ_by_cand:
                    occupant = weapon_retarget.find_target_occupant(game_dir, c)
                    occ_by_cand[c.key] = [str(occupant.relative_to(Path(game_dir)))] if occupant else []
                occ_note = self._occupied_note(state["fluffy_index"], occ_by_cand.get(c.key, []))
                note = f"{note} {occ_note}".strip() if note else occ_note
                cand_tree.insert("", "end", iid=c.key,
                                  values=(weapon_retarget.weapon_label(c.key, lang), grade_text[c.grade], note),
                                  tags=(c.grade,))
            btn_apply.configure(state="normal" if cands else "disabled")
            btn_leave.configure(state="normal")
            existing = state["assignments"].get(key)
            if existing is not None:
                dst_key = f"it{existing[0]}/{existing[1]}/{existing[2]}"
                if cand_tree.exists(dst_key):
                    cand_tree.selection_set(dst_key)

        def on_slot_selected(_event=None):
            sel = slot_tree.selection()
            if sel:
                _select_slot(sel[0])

        def do_apply_to_slot():
            key = state["active_key"]
            sel = cand_tree.selection()
            if key is None or not sel:
                messagebox.showinfo(APP_TITLE, t("msg_weapon_retarget_select_target"), parent=win)
                return
            cand = next(c for c in state["candidates_by_key"][key] if c.key == sel[0])
            if cand.grade == "refused":
                messagebox.showerror(APP_TITLE, t("msg_weapon_retarget_refused_blocked"), parent=win)
                return
            state["assignments"][key] = (cand.type_code, cand.sid, cand.iid)
            _refresh_slot_row(key)
            _refresh_generate_enabled()

        def do_leave_unchanged():
            key = state["active_key"]
            if key is None:
                messagebox.showinfo(APP_TITLE, t("msg_weapon_retarget_pick_first"), parent=win)
                return
            state["assignments"][key] = None
            _refresh_slot_row(key)
            _refresh_generate_enabled()

        def do_generate():
            groups = state["groups"]
            assignments = state["assignments"]
            if not groups or not all(g.key in assignments for g in groups):
                messagebox.showinfo(APP_TITLE, t("msg_weapon_retarget_incomplete"), parent=win)
                return
            if not Path(self.game_dir.get()).is_dir():
                messagebox.showerror(APP_TITLE, t("err_no_game_dir"), parent=win)
                return
            game = GameArchive(self.game_dir.get(), log=lambda *a, **k: None)
            unverified = []
            occupant_relpaths_all = []
            for g in groups:
                dst = assignments[g.key]
                if dst is None:
                    continue
                dst_key = f"it{dst[0]}/{dst[1]}/{dst[2]}"
                cand = next((c for c in state["candidates_by_key"].get(g.key, []) if c.key == dst_key), None)
                if cand is None:
                    cand = weapon_retarget.TargetWeaponCandidate(
                        key=dst_key, type_code=dst[0], sid=dst[1], iid=dst[2], grade="exact")
                ok, missing = weapon_retarget.verify_target_vanilla(game, g, cand)
                if not ok:
                    unverified.append(f"{g.key} -> {dst_key}: {', '.join(missing)}")
                occupant_relpaths_all.extend(state["occupancy_by_key"].get(g.key, {}).get(dst_key, []))
            if unverified and not messagebox.askyesno(
                    APP_TITLE, t("ask_retarget_unverified", missing="\n".join(unverified)), parent=win):
                return
            if occupant_relpaths_all and not self._confirm_occupied(
                    state["fluffy_index"], occupant_relpaths_all, win):
                return
            src_stem = state.get("_page_name") or Path(file_var.get()).stem
            out_path = filedialog.asksaveasfilename(
                title=t("dlg_save_weapon_retarget"), defaultextension=".zip",
                initialfile=f"{src_stem} (retargeted).zip",
                filetypes=[(t("filetype_zip"), "*.zip")],
            )
            if not out_path:
                return
            btn_generate.configure(state="disabled")
            btn_pick.configure(state="disabled")
            status_var.set(t("msg_retarget_generating"))

            # A page picked out of a multi-page archive was already
            # extracted AND repaired into its own standalone directory
            # (_extract_and_repair_page()) -- pass that straight through
            # instead of re-extracting the ORIGINAL, still-multi-page
            # archive from scratch (retarget_archive_multi() accepts a
            # plain directory just as readily as an archive path, and
            # skips its own extraction step entirely when given one).
            # password is only meaningful for the original-archive path;
            # an already-extracted directory needs none.
            effective_root = state.get("effective_mod_root")
            source_for_generate = effective_root if effective_root is not None else Path(file_var.get())
            password_for_generate = None if effective_root is not None else state.get("archive_password")

            def worker():
                try:
                    weapon_retarget.retarget_archive_multi(
                        source_for_generate, Path(out_path), assignments, log=lambda s: None,
                        password=password_for_generate)
                except Exception as exc:
                    err_text = t("err_unhandled", e=exc)  # format now -- exc unbinds when this block exits
                    win.after(0, lambda: (messagebox.showerror(APP_TITLE, err_text, parent=win),
                                          status_var.set(""), btn_pick.configure(state="normal"),
                                          _refresh_generate_enabled()))
                    return
                win.after(0, lambda: (status_var.set(""), btn_pick.configure(state="normal"),
                                      _refresh_generate_enabled(),
                                      messagebox.showinfo(APP_TITLE, t("msg_weapon_retarget_done", path=out_path),
                                                           parent=win)))

            threading.Thread(target=worker, daemon=True).start()

        btn_pick.configure(command=do_pick)
        slot_tree.bind("<<TreeviewSelect>>", on_slot_selected)
        btn_apply.configure(command=do_apply_to_slot)
        btn_leave.configure(command=do_leave_unchanged)
        btn_generate.configure(command=do_generate)

        def refresh_texts():
            """Same pattern as _open_retarget_dialog()'s own refresh hook --
            called from App._retranslate() when the language changes while
            this dialog is open."""
            win.title(t("dlg_weapon_retarget_title"))
            file_label.configure(text=t("lbl_retarget_file"))
            btn_pick.configure(text=t("btn_choose_file"))
            slots_frame.configure(text=t("lbl_weapon_retarget_slots"))
            cand_frame.configure(text=t("lbl_weapon_retarget_targets"))
            for col, key in [("weapon", "col_weapon"), ("files", "col_files"), ("status", "col_status")]:
                slot_tree.heading(col, text=t(key))
            for col, key in [("weapon", "col_weapon"), ("grade", "col_compat"), ("note", "col_note")]:
                cand_tree.heading(col, text=t(key))
            btn_apply.configure(text=t("btn_apply_to_slot"))
            btn_leave.configure(text=t("btn_leave_unchanged"))
            btn_generate.configure(text=t("btn_generate_retarget"))
            btn_close.configure(text=t("btn_close"))

            lang = i18n.get_language()
            if state["groups"]:
                info_label.configure(text=t("msg_weapon_retarget_multi_summary",
                                             count=len(state["groups"]), unmatched=len(state["unmatched"])))
            elif not file_var.get():
                info_label.configure(text=t("msg_weapon_retarget_no_file"))

            for g in state["groups"]:
                status_text, tag = _status_text_for(g.key)
                slot_tree.item(g.key, values=(weapon_retarget.weapon_label(g.key, lang), len(g.files), status_text),
                                tags=(tag,))

            active = state["active_key"]
            if active and active in state["candidates_by_key"]:
                grade_text = {"exact": t("grade_weapon_exact"), "partial": t("grade_weapon_partial"),
                              "refused": t("grade_weapon_refused")}
                occ_by_cand = state["occupancy_by_key"].get(active, {})
                for c in state["candidates_by_key"][active]:
                    note = _weapon_note_for(c)
                    occ_note = self._occupied_note(state["fluffy_index"], occ_by_cand.get(c.key, []))
                    note = f"{note} {occ_note}".strip() if note else occ_note
                    cand_tree.item(c.key, values=(weapon_retarget.weapon_label(c.key, lang),
                                                   grade_text[c.grade], note), tags=(c.grade,))

        self._weapon_retarget_refresh_fn = refresh_texts

    def _browse_game_dir(self):
        d = filedialog.askdirectory(title=t("dlg_choose_game_dir"))
        if d:
            self.game_dir.set(d)

    def _browse_fluffy_dir(self):
        d = filedialog.askdirectory(title=t("dlg_choose_fluffy_dir"))
        if d:
            self.fluffy_dir.set(d)

    def _load_fluffy_index(self):
        """Parses Fluffy's installed.ini fresh (cheap -- a plain text
        file, no reason to cache across dialog sessions) if a Fluffy path
        is configured and looks valid; {} otherwise (silently -- an
        unconfigured/wrong Fluffy path just means occupancy notes fall
        back to the generic "another mod" wording instead of naming it,
        never an error)."""
        import fluffy_installed
        fdir = self.fluffy_dir.get()
        if not fdir:
            return {}
        ini_path = fluffy_installed.installed_ini_path(fdir)
        if not ini_path.is_file():
            return {}
        return fluffy_installed.parse_installed_ini(ini_path)

    def _confirm_occupied(self, fluffy_index: dict, occupant_relpaths: list[str], parent_win) -> bool:
        """Popup shown at Generate time (not just the inline list note)
        when the selected target slot is already occupied -- selection
        itself stays unrestricted (per the user's own explicit call,
        2026-08-10: warn, don't block), this is the one point where
        proceeding needs an explicit yes. Returns True to proceed."""
        import fluffy_installed
        names = set()
        for p in occupant_relpaths:
            names.update(fluffy_installed.find_occupant_names(fluffy_index, p))
        mod_suffix = t("mod_suffix_named", mod=", ".join(sorted(names))) if names else ""
        return messagebox.askyesno(
            APP_TITLE, t("ask_confirm_target_occupied", mod_suffix=mod_suffix), parent=parent_win)

    def _occupied_note(self, fluffy_index: dict, occupant_relpaths: list[str]) -> str:
        """occupant_relpaths: natives/-relative paths of loose files
        already found sitting at a candidate target's slot (empty list
        means free -- see game_archive.find_loose_files). Returns "" if
        free, else a note naming the occupying mod when Fluffy's
        installed.ini resolves it, or a generic warning when it doesn't
        (no Fluffy path configured, or the file wasn't Fluffy-deployed)."""
        import fluffy_installed
        if not occupant_relpaths:
            return ""
        names = set()
        for p in occupant_relpaths:
            names.update(fluffy_installed.find_occupant_names(fluffy_index, p))
        if names:
            return t("note_target_occupied_named", mod=", ".join(sorted(names)))
        return t("note_target_occupied")

    def _browse_mod(self):
        files = filedialog.askopenfilenames(
            title=t("dlg_choose_mod"),
            filetypes=[(t("filetype_archives"), "*.zip *.7z *.rar"), (t("filetype_allfiles"), "*.*")],
        )
        for f in files:
            self._enqueue(Path(f))

    def _on_drop(self, event):
        for raw in self.root.tk.splitlist(event.data):
            self._enqueue(Path(raw))

    def _enqueue(self, path: Path):
        if path.is_dir():
            for p in sorted(path.rglob("*")):
                if p.suffix.lower() in ARCHIVE_EXTS:
                    self._enqueue(p)
            return
        if path.suffix.lower() not in ARCHIVE_EXTS:
            self.log(f"[skip] unsupported file type: {path.name}")
            return
        if path in self.mod_queue:
            return
        self.mod_queue.append(path)
        self.mod_listbox.insert("end", path.name)

    def _remove_selected(self):
        for i in reversed(self.mod_listbox.curselection()):
            self.mod_listbox.delete(i)
            del self.mod_queue[i]

    def _clear_queue(self):
        self.mod_listbox.delete(0, "end")
        self.mod_queue.clear()

    # ---- logging / thread-safe UI updates -----------------------------

    def log(self, msg: str):
        self._log_queue.put(msg)
        try:
            self._log_fh.write(msg + "\n")
            self._log_fh.flush()
        except (OSError, ValueError):
            pass

    def set_status(self, msg: str):
        """Thread-safe status update -- tk.StringVar.set() drives a Tk label
        via the Tcl interpreter, which is not safe to touch off the main
        thread (unlike log(), which only queues a plain string)."""
        self._run_on_main_thread(self.status.set, msg)

    def set_progress(self, phase: str, done: int, total: int):
        """Thread-safe, non-blocking progress update -- called from the
        worker thread, possibly many times a second on a large pak mod
        (see pak_mod_fix.py's _PROGRESS_STEP), so this must NOT round-trip
        through _run_on_main_thread like set_status() does (that blocks the
        calling thread until the main thread services it, which would slow
        the scan down for no benefit at this call frequency). Queued the
        same way log() is; _poll_queues() only applies the latest one."""
        self._progress_queue.put((phase, done, total))

    def _reset_progress(self):
        self.progress_bar.configure(value=0)
        self.progress_pct_label.configure(text="")

    def _poll_queues(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get()
            self.log_text.configure(state="normal")
            tag = _log_tag_for(msg)
            self.log_text.insert("end", msg + "\n", *((tag,) if tag else ()))
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        latest_progress = None
        while not self._progress_queue.empty():
            latest_progress = self._progress_queue.get()  # only the newest matters -- drop any backlog
        if latest_progress is not None:
            phase, done, total = latest_progress
            pct = round(done / total * 100) if total else 0
            self.progress_bar.configure(value=pct)
            self.progress_pct_label.configure(text=f"{pct}% ({t('progress_phase_' + phase)})")

        while not self._main_thread_queue.empty():
            fn, args, result_holder, event = self._main_thread_queue.get()
            try:
                result_holder.append(fn(*args))
            except Exception as e:
                result_holder.append(e)
            event.set()

        self.root.after(80, self._poll_queues)

    def _run_on_main_thread(self, fn, *args):
        """Blocks the calling (worker) thread until fn() has run on the
        Tk main thread and returns its result. Needed because tkinter
        dialogs (messagebox/filedialog) aren't safe to call off-thread."""
        result_holder = []
        event = threading.Event()
        self._main_thread_queue.put((fn, args, result_holder, event))
        event.wait()
        r = result_holder[0]
        if isinstance(r, Exception):
            raise r
        return r

    def ask_yes_no(self, title: str, message: str) -> bool:
        return self._run_on_main_thread(messagebox.askyesno, title, message)

    def ask_password(self, title: str, message: str) -> str | None:
        return self._run_on_main_thread(
            lambda: simpledialog.askstring(title, message, show="*", parent=self.root))

    def extract_archive_prompting(self, archive_path: Path, dest_dir: Path) -> tuple[Path, str | None]:
        """`extract_archive()`, but transparently prompts for a password
        (via `ask_password()`, safe to call from any background thread --
        see `_run_on_main_thread()`) and retries on `PasswordRequired`
        instead of failing outright. Raises `PasswordRequired` if the user
        cancels the prompt, matching the underlying function's own
        "couldn't extract" signal for callers that don't care why.

        Returns `(mod_root, password)` -- the resolved password (`None` if
        the archive never needed one) is handed back so a caller that
        re-extracts the SAME archive later (both retarget dialogs' "Generate"
        step does exactly this, from a fresh temp dir via
        `retarget_archive_multi()`) doesn't have to prompt the user twice
        for one archive."""
        password = None
        while True:
            try:
                return extract_archive(archive_path, dest_dir, password=password), password
            except PasswordRequired as e:
                msg_key = "ask_archive_password_wrong" if e.wrong_password else "ask_archive_password"
                password = self.ask_password(t("dlg_archive_password_title"), t(msg_key, name=archive_path.name))
                if not password:
                    raise

    def show_info(self, title: str, message: str):
        self._run_on_main_thread(messagebox.showinfo, title, message)

    def show_error(self, title: str, message: str):
        self._run_on_main_thread(messagebox.showerror, title, message)

    def ask_save_dir(self, title: str) -> str:
        return self._run_on_main_thread(lambda: filedialog.askdirectory(title=title))

    # ---- main action ---------------------------------------------------

    def _start(self):
        if self._busy:
            return
        if not self.mod_queue:
            messagebox.showwarning(APP_TITLE, t("warn_no_mod"))
            return
        if not Path(self.game_dir.get()).is_dir():
            messagebox.showwarning(APP_TITLE, t("warn_bad_game_dir"))
            return
        self._busy = True
        self.start_btn.configure(state="disabled")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        self._run_on_main_thread(self.notice_verifying.set, t("notice_verifying"))
        try:
            game_dir = Path(self.game_dir.get())
            self.set_status(t("status_indexing"))
            self.log("Indexing current game version's files (slow only the first time, cached after)...")
            game = GameArchive(game_dir, log=self.log)

            queue_snapshot = list(self.mod_queue)
            total = len(queue_snapshot)
            # Asked ONCE up front, not per mod -- with a multi-mod queue,
            # a save-location prompt after every single file was the #1
            # reported annoyance. Every fixed mod in this run lands in the
            # same folder as its own "<name>_fixed.zip", so there's no
            # collision risk even with many queued at once.
            save_dir = self.ask_save_dir(t("dlg_choose_save_dir_batch"))
            if not save_dir:
                self.log("No save location chosen -- aborting batch.")
                return

            batch = {"fixed": 0, "already_current": 0, "unresolved": 0, "unresolved_parts": 0,
                     "partial_materials": 0, "errors": 0, "textures_restored": 0}
            for i, mod_archive in enumerate(queue_snapshot, start=1):
                self.set_status(t("status_processing", i=i, total=total, name=mod_archive.name))
                self.log(f"\n{'=' * 60}\n[{i}/{total}] {mod_archive.name}")
                self._run_on_main_thread(self._reset_progress)
                try:
                    outcome = self._run_one(mod_archive, game, save_dir)
                    batch[outcome] = batch.get(outcome, 0) + 1
                except Exception as e:
                    self.log(f"[error] {mod_archive.name}: {e}\n{traceback.format_exc()}")
                    batch["errors"] += 1

            msg = t(
                "msg_batch_done", total=total, fixed=batch["fixed"],
                already_current=batch["already_current"], unresolved=batch["unresolved"],
                errors=batch["errors"], out=save_dir,
            )
            if batch["unresolved_parts"]:
                msg += "\n\n" + t("msg_unresolved_parts_hint", count=batch["unresolved_parts"])
            if batch["partial_materials"]:
                msg += "\n\n" + t("msg_partial_materials_hint", count=batch["partial_materials"])
            self.show_info(APP_TITLE, msg)
        except Exception as e:
            self.log(f"[error] {e}\n{traceback.format_exc()}")
            self.show_error(APP_TITLE, t("err_unhandled", e=e))
        finally:
            self._busy = False
            self._run_on_main_thread(lambda: self.start_btn.configure(state="normal"))
            self._run_on_main_thread(self.notice_verifying.set, "")
            self._run_on_main_thread(self._reset_progress)
            self.set_status(t("status_done"))

    def _run_one(self, mod_archive: Path, game: GameArchive, save_dir: str) -> str:
        """Fully unattended -- no per-mod prompts. Returns one of "fixed",
        "already_current", "unresolved" for the caller to tally."""
        self.log(f"Extracting: {mod_archive.name}")
        work_dir = Path(tempfile.mkdtemp(prefix="mhwmodfix_"))
        mod_root, _ = self.extract_archive_prompting(mod_archive, work_dir)

        self.log("Diagnosing mod state...")
        file_plans, pak_plans = diagnose(mod_root, game, progress_cb=self.set_progress)
        summary = summarize((file_plans, pak_plans))
        self.log(summary)

        all_plans = list(file_plans) + [p for p in pak_plans if p.applicable]
        unresolved_plans = [p for p in all_plans if p.unresolved]
        # A loose .mdf2 with SOME unresolved materials can still have
        # others worth fixing (process_mod() does that material-by-
        # material now) -- so needs_rebuild alone decides whether there's
        # a fix to write, independent of unresolved. pak_plans don't have
        # this per-material split, so `not p.unresolved` still applies to
        # them via needs_rebuild's own definition there.
        needs_fix = [p for p in all_plans if p.needs_rebuild]

        # "nothing to fix" and "couldn't determine" are NOT the same thing --
        # a file with an unresolved material means we have no safe way to
        # tell whether it's current or stale, so it must never be reported
        # as "already up to date" (that previously happened here: a file
        # with 9/10 materials safely matched and 1 unresolved was shown as
        # "already latest version" even though the tool genuinely couldn't
        # verify it).
        #
        # A mod whose CONTENT needs nothing fixed can still be worth
        # producing output for, if its Fluffy page structure does --
        # confirmed real case: a mod author (Mangie) who tests via MO2
        # (which has no concept of Fluffy's page-selector at all) ships
        # content that's already fully current but with extra pieces as
        # loose top-level files Fluffy can't offer as install options.
        # Before this check, this whole function would report
        # "already up to date" here and produce NO output at all, even
        # for a user whose only actual need was the structural fix.
        needs_repack = needs_repackaging(mod_root)
        if not needs_fix and not unresolved_plans and not needs_repack:
            shutil.rmtree(work_dir, ignore_errors=True)
            self.log(f"{mod_archive.name}: already up to date, nothing to fix.")
            return "already_current"

        if not needs_fix:
            # Either every remaining issue is a genuinely unresolved (no
            # safe donor) part diagnose() already found, or -- per the
            # comment above -- content is already fully current and only
            # the Fluffy structure needs fixing. Either way there's
            # nothing for process_mod() itself to do, so skip straight to
            # a plain copy + repackage rather than running the full
            # (here, no-op) repair pipeline.
            output_root = work_dir.parent / (work_dir.name + "_fixed")
            shutil.copytree(mod_root, output_root)
            repackaged = repackage_for_fluffy(output_root, log=self.log)
            if not repackaged:
                shutil.rmtree(work_dir, ignore_errors=True)
                shutil.rmtree(output_root, ignore_errors=True)
                self.log(f"{mod_archive.name}: nothing could be safely auto-repaired "
                         f"({len(unresolved_plans)} unresolved) -- left untouched.")
                return "unresolved"
            if unresolved_plans:
                self.log(f"{mod_archive.name}: content has {len(unresolved_plans)} part(s) left as "
                         f"shipped (no safe donor found), but the Fluffy page structure was fixed so "
                         f"every piece can still be installed/selected normally.")
            else:
                self.log(f"{mod_archive.name}: content is already up to date -- only the Fluffy page "
                         f"structure needed fixing.")
            out_zip = Path(save_dir) / (mod_archive.stem + "_fixed.zip")
            self.log(f"Zipping: {out_zip}")
            zip_folder(output_root, out_zip)
            shutil.rmtree(work_dir, ignore_errors=True)
            shutil.rmtree(output_root, ignore_errors=True)
            return "fixed"

        output_root = work_dir.parent / (work_dir.name + "_fixed")
        shutil.copytree(mod_root, output_root)
        force_unresolved = self.force_unresolved.get()
        preserve_extra = self.preserve_extra.get()
        shader_migration = self.shader_migration.get()
        stats = process_mod(mod_root, output_root, game, allow_cross_piece=True, log=self.log,
                             force_unresolved_pfbs=force_unresolved,
                             preserve_extra_pfb_components=preserve_extra,
                             experimental_shader_migration=shader_migration,
                             progress_cb=self.set_progress)
        repackage_for_fluffy(output_root, log=self.log)

        self.log(f"done: fixed={stats['fixed']} already_current={stats['already_current']} "
                 f"skipped={stats['skipped']} errors={stats['errors']} "
                 f"texture_paths_restored={stats['textures_restored']}")

        # pfb_unresolved > 0 means at least one piece was left as the mod's
        # own original (possibly-stale) content -- confirmed via real
        # in-game testing (Mangie "Snow Trigger") that this can silently
        # cause a hard hang at boot when that piece is equipped, not just a
        # visual glitch, so this is surfaced clearly rather than buried in
        # the scrolling log.
        if stats.get("pfb_unresolved") and not force_unresolved:
            self.log(f"    [!] {mod_archive.name}: {stats['pfb_unresolved']} part(s) couldn't be "
                     f"safely auto-repaired and were left as the mod's original files. This can range "
                     f"from a cosmetic glitch to the game hanging on load when that part is equipped. "
                     f"Try re-running with \"{t('chk_force_unresolved')}\" checked, then verify "
                     f"in-game before trusting the result.")

        # Distinct from pfb_unresolved above: a material with literally no
        # vanilla file anywhere in the game using its shader has no donor
        # to force-fix against at all (confirmed real case: "Endfield
        # LiJiyan", Base_GOLD_Push.mmtr, 0 candidates game-wide) -- so this
        # does NOT suggest the force-fix checkbox, which only helps pfb
        # structural mismatches, not "no template exists" for a material.
        if stats.get("materials_left_unresolved"):
            self.log(f"    [!] {mod_archive.name}: {stats['materials_left_unresolved']} material(s) had no "
                     f"safe donor anywhere in the game and were left exactly as shipped; everything else "
                     f"in the same file(s) was still fixed.")

        # Diagnostic-only, can't be auto-fixed (would need to edit mesh
        # geometry data, out of scope) -- see mesh_check.py. Surfaced as
        # its own summary line, same as materials_left_unresolved above,
        # since the per-mismatch detail already went into the log during
        # processing and could easily scroll past unnoticed.
        if stats.get("mesh_mdf2_mismatches"):
            self.log(f"    [!] {mod_archive.name}: {stats['mesh_mdf2_mismatches']} mesh/mdf2 material "
                     f"mismatch(es) found -- these are a pre-existing issue in the mod's own files this "
                     f"tool can't fix (would need to edit mesh geometry data), and are very likely to "
                     f"cause a black screen or checkerboard texture for the affected piece(s) in-game.")

        out_zip = Path(save_dir) / (mod_archive.stem + "_fixed.zip")
        self.log(f"Zipping: {out_zip}")
        zip_folder(output_root, out_zip)

        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(output_root, ignore_errors=True)
        if stats.get("pfb_unresolved") and not force_unresolved:
            return "unresolved_parts"
        if stats.get("materials_left_unresolved"):
            return "partial_materials"
        return "fixed"


def _acquire_single_instance_lock():
    """Windows named mutex: returns True if this is the only running
    instance. The handle is deliberately never closed/released -- it needs
    to live for the whole process lifetime so Windows drops it (and frees
    the name for the next launch) only on exit/crash, not the moment this
    function returns."""
    import ctypes

    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "Local\\MHWmodfixer_by_Littlefish_SingleInstance")
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _install_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _is_ascii_path(p: Path) -> bool:
    try:
        str(p).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def main():
    i18n.set_language(i18n.load_saved_language())

    if not _acquire_single_instance_lock():
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(APP_TITLE, f"{APP_TITLE} {t('warn_single_instance')}")
        return

    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    try:
        _apply_theme(root)
    except Exception:
        pass

    install_dir = _install_dir()
    if not _is_ascii_path(install_dir):
        messagebox.showwarning(APP_TITLE, t("warn_non_ascii_path", path=str(install_dir)))

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
