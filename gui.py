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
from tkinter import BooleanVar, StringVar, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

import i18n
from archive_extract import extract_archive
from auto_fix import DEFAULT_GAME_DIR, process_mod
from diagnose import diagnose, summarize
from fluffy_repackage import repackage_for_fluffy
from game_archive import GameArchive
from i18n import t

APP_TITLE = "MHWmodfixer by Littlefish (PoeticJustice79)"
ARCHIVE_EXTS = {".zip", ".7z", ".rar"}
LOG_DIR = Path.home() / "AppData" / "Local" / "MHWmodfixer" / "logs"


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
        self.status = StringVar(value=t("status_default"))
        self.lang_display = StringVar(value=i18n.LANGUAGES[i18n.get_language()])
        self.force_unresolved = BooleanVar(value=False)
        self.preserve_extra = BooleanVar(value=False)
        self.mod_queue: list[Path] = []

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

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill="x", **pad)
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

        list_label_frame = ttk.Frame(self.root)
        list_label_frame.pack(fill="x", padx=10)
        self.lbl_mod_list = ttk.Label(list_label_frame, text=t("lbl_mod_list"))
        self.lbl_mod_list.pack(side="left")

        list_frame = ttk.Frame(self.root)
        list_frame.pack(fill="both", padx=10, pady=4)
        self.mod_listbox = tk.Listbox(list_frame, height=6, selectmode="extended")
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

        options_frame = ttk.Frame(self.root)
        options_frame.pack(fill="x", padx=10, pady=(0, 2))
        self.chk_force_unresolved = ttk.Checkbutton(
            options_frame, text=t("chk_force_unresolved"), variable=self.force_unresolved,
        )
        self.chk_force_unresolved.pack(side="left")
        self.chk_preserve_extra = ttk.Checkbutton(
            options_frame, text=t("chk_preserve_extra"), variable=self.preserve_extra,
        )
        self.chk_preserve_extra.pack(side="left", padx=(12, 0))

        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", **pad)
        self.start_btn = ttk.Button(action_frame, text=t("btn_start"), command=self._start)
        self.start_btn.pack(side="left")
        self.btn_open_log = ttk.Button(action_frame, text=t("btn_open_log_folder"), command=self._open_log_folder)
        self.btn_open_log.pack(side="left", padx=6)

        ttk.Label(self.root, textvariable=self.status).pack(fill="x", padx=10)

        self.notice_verifying = StringVar(value="")
        self.lbl_notice = ttk.Label(self.root, textvariable=self.notice_verifying, foreground="#a15c00")
        self.lbl_notice.pack(fill="x", padx=10)

        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill="x", padx=10, pady=(0, 4))
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True)
        self.progress_pct_label = ttk.Label(progress_frame, text="", width=6, anchor="e")
        self.progress_pct_label.pack(side="left", padx=(6, 0))

        self.log_text = ScrolledText(self.root, height=16, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)

    def _on_lang_change(self, event=None):
        code = next((c for c, name in i18n.LANGUAGES.items() if name == self.lang_display.get()), "en")
        i18n.set_language(code)
        i18n.save_language(code)
        self._retranslate()

    def _retranslate(self):
        self.lbl_lang.configure(text=t("lbl_lang"))
        self.lbl_game_dir.configure(text=t("lbl_game_dir"))
        self.btn_browse_game.configure(text=t("btn_browse_game"))
        self.lbl_mod_list.configure(text=t("lbl_mod_list"))
        self.btn_add_mod.configure(text=t("btn_add_mod"))
        self.btn_remove_selected.configure(text=t("btn_remove_selected"))
        self.btn_clear_all.configure(text=t("btn_clear_all"))
        self.chk_force_unresolved.configure(text=t("chk_force_unresolved"))
        self.chk_preserve_extra.configure(text=t("chk_preserve_extra"))
        self.start_btn.configure(text=t("btn_start"))
        self.btn_open_log.configure(text=t("btn_open_log_folder"))
        if self._busy:
            self.notice_verifying.set(t("notice_verifying"))
        else:
            self.status.set(t("status_default"))

    def _open_log_folder(self):
        try:
            os.startfile(LOG_DIR)
        except OSError:
            pass

    def _browse_game_dir(self):
        d = filedialog.askdirectory(title=t("dlg_choose_game_dir"))
        if d:
            self.game_dir.set(d)

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
            self.log_text.insert("end", msg + "\n")
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
                     "errors": 0, "textures_restored": 0}
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
        mod_root = extract_archive(mod_archive, work_dir)

        self.log("Diagnosing mod state...")
        file_plans, pak_plans = diagnose(mod_root, game, progress_cb=self.set_progress)
        summary = summarize((file_plans, pak_plans))
        self.log(summary)

        all_plans = list(file_plans) + [p for p in pak_plans if p.applicable]
        unresolved_plans = [p for p in all_plans if p.unresolved]
        needs_fix = [p for p in all_plans if not p.unresolved and p.needs_rebuild]

        # "nothing to fix" and "couldn't determine" are NOT the same thing --
        # a file with an unresolved material means we have no safe way to
        # tell whether it's current or stale, so it must never be reported
        # as "already up to date" (that previously happened here: a file
        # with 9/10 materials safely matched and 1 unresolved was shown as
        # "already latest version" even though the tool genuinely couldn't
        # verify it).
        if not needs_fix and not unresolved_plans:
            shutil.rmtree(work_dir, ignore_errors=True)
            self.log(f"{mod_archive.name}: already up to date, nothing to fix.")
            return "already_current"

        if not needs_fix and unresolved_plans:
            shutil.rmtree(work_dir, ignore_errors=True)
            self.log(f"{mod_archive.name}: nothing could be safely auto-repaired "
                     f"({len(unresolved_plans)} unresolved) -- left untouched.")
            return "unresolved"

        output_root = work_dir.parent / (work_dir.name + "_fixed")
        shutil.copytree(mod_root, output_root)
        force_unresolved = self.force_unresolved.get()
        preserve_extra = self.preserve_extra.get()
        stats = process_mod(mod_root, output_root, game, allow_cross_piece=True, log=self.log,
                             force_unresolved_pfbs=force_unresolved,
                             preserve_extra_pfb_components=preserve_extra,
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

        out_zip = Path(save_dir) / (mod_archive.stem + "_fixed.zip")
        self.log(f"Zipping: {out_zip}")
        zip_folder(output_root, out_zip)

        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(output_root, ignore_errors=True)
        if stats.get("pfb_unresolved") and not force_unresolved:
            return "unresolved_parts"
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
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass

    install_dir = _install_dir()
    if not _is_ascii_path(install_dir):
        messagebox.showwarning(APP_TITLE, t("warn_non_ascii_path", path=str(install_dir)))

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
