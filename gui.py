"""
MHWmodfixer by Littlefish -- GUI front-end.

Mod archives can be dropped onto the window (or picked via the file
dialog, multi-select is fine too) and are queued up; "복구 시작" walks the
queue and fixes them one at a time, in order. Each one still gets its own
"here's what's stale, proceed?" confirmation and its own "where do you
want to save the result?" prompt, same as the single-file flow -- just
looped automatically instead of requiring the file to be re-picked by hand
each time.
"""
from __future__ import annotations

import queue
import shutil
import tempfile
import threading
import traceback
import zipfile
from pathlib import Path

import tkinter as tk
from tkinter import StringVar, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

from archive_extract import extract_archive
from auto_fix import DEFAULT_GAME_DIR, process_mod
from diagnose import diagnose, summarize
from fluffy_repackage import repackage_for_fluffy
from game_archive import GameArchive

APP_TITLE = "MHWmodfixer by Littlefish"
ARCHIVE_EXTS = {".zip", ".7z", ".rar"}


def zip_folder(src_folder: Path, dest_zip: Path):
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in src_folder.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(src_folder))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("760x600")
        root.minsize(600, 440)

        self.game_dir = StringVar(value=DEFAULT_GAME_DIR if Path(DEFAULT_GAME_DIR).is_dir() else "")
        self.status = StringVar(value="모드 압축파일을 끌어다 놓거나 선택하세요")
        self.mod_queue: list[Path] = []

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._main_thread_queue: queue.Queue[tuple] = queue.Queue()
        self._busy = False

        self._build_ui()
        self._poll_queues()

    # ---- UI layout ---------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        game_frame = ttk.Frame(self.root)
        game_frame.pack(fill="x", **pad)
        ttk.Label(game_frame, text="게임 폴더:").pack(side="left")
        ttk.Entry(game_frame, textvariable=self.game_dir).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(game_frame, text="변경", command=self._browse_game_dir).pack(side="left")

        list_label_frame = ttk.Frame(self.root)
        list_label_frame.pack(fill="x", padx=10)
        ttk.Label(list_label_frame, text="모드 압축파일 목록 (여기로 끌어다 놓기 가능):").pack(side="left")

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
        ttk.Button(btn_frame, text="추가 (zip/7z/rar)", command=self._browse_mod).pack(side="left")
        ttk.Button(btn_frame, text="선택 제거", command=self._remove_selected).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="전체 지우기", command=self._clear_queue).pack(side="left")

        self.start_btn = ttk.Button(self.root, text="복구 시작", command=self._start)
        self.start_btn.pack(**pad)

        ttk.Label(self.root, textvariable=self.status).pack(fill="x", padx=10)

        self.log_text = ScrolledText(self.root, height=16, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)

    def _browse_game_dir(self):
        d = filedialog.askdirectory(title="Monster Hunter Wilds 설치 폴더 선택")
        if d:
            self.game_dir.set(d)

    def _browse_mod(self):
        files = filedialog.askopenfilenames(
            title="모드 압축파일 선택 (여러 개 선택 가능)",
            filetypes=[("Archives", "*.zip *.7z *.rar"), ("All files", "*.*")],
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
            self.log(f"[무시] 지원하지 않는 파일 형식: {path.name}")
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

    def set_status(self, msg: str):
        """Thread-safe status update -- tk.StringVar.set() drives a Tk label
        via the Tcl interpreter, which is not safe to touch off the main
        thread (unlike log(), which only queues a plain string)."""
        self._run_on_main_thread(self.status.set, msg)

    def _poll_queues(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get()
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

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
            messagebox.showwarning(APP_TITLE, "모드 압축파일을 먼저 추가하세요.")
            return
        if not Path(self.game_dir.get()).is_dir():
            messagebox.showwarning(APP_TITLE, "게임 폴더 경로가 올바르지 않습니다.")
            return
        self._busy = True
        self.start_btn.configure(state="disabled")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            game_dir = Path(self.game_dir.get())
            self.set_status("게임 파일 인덱싱 중...")
            self.log("현재 게임 버전 파일 인덱싱 중 (처음 한 번만 느리고, 이후엔 캐시로 빠름)...")
            game = GameArchive(game_dir, log=self.log)

            queue_snapshot = list(self.mod_queue)
            total = len(queue_snapshot)
            for i, mod_archive in enumerate(queue_snapshot, start=1):
                self.set_status(f"처리 중 ({i}/{total}): {mod_archive.name}")
                self.log(f"\n{'=' * 60}\n[{i}/{total}] {mod_archive.name}")
                try:
                    self._run_one(mod_archive, game)
                except Exception as e:
                    self.log(f"[오류] {mod_archive.name}: {e}\n{traceback.format_exc()}")
                    self.show_error(APP_TITLE, f"{mod_archive.name} 처리 중 오류:\n{e}")
        except Exception as e:
            self.log(f"[오류] {e}\n{traceback.format_exc()}")
            self.show_error(APP_TITLE, f"오류가 발생했습니다:\n{e}")
        finally:
            self._busy = False
            self._run_on_main_thread(lambda: self.start_btn.configure(state="normal"))
            self.set_status("완료 -- 목록을 정리하거나 새 모드를 추가하세요")

    def _run_one(self, mod_archive: Path, game: GameArchive):
        self.log(f"압축 해제: {mod_archive.name}")
        work_dir = Path(tempfile.mkdtemp(prefix="mhwmodfix_"))
        mod_root = extract_archive(mod_archive, work_dir)

        self.log("모드 상태 진단 중...")
        file_plans, pak_plans = diagnose(mod_root, game)
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
            self.show_info(APP_TITLE, f"[{mod_archive.name}] 이미 최신 버전입니다. 고칠 게 없습니다.\n\n" + summary)
            return

        if not needs_fix and unresolved_plans:
            shutil.rmtree(work_dir, ignore_errors=True)
            self.show_info(
                APP_TITLE,
                f"[{mod_archive.name}] 자동으로 안전하게 복구할 수 있는 부분이 없습니다.\n\n"
                f"{len(unresolved_plans)}개 파일(또는 그 안의 일부 머티리얼)에서 안전하게 매칭되는 "
                f"바닐라 도너를 찾지 못해, 이미 최신인지조차 확인할 수 없습니다. 이 모드는 그대로 두었습니다.\n\n"
                + summary,
            )
            return

        confirm_msg = f"[{mod_archive.name}]\n{len(needs_fix)}개 파일이 구버전입니다. 업데이트를 진행할까요?"
        if unresolved_plans:
            confirm_msg += (f"\n(참고: {len(unresolved_plans)}개는 도너를 찾지 못해 확인이 안 되어 "
                             f"그대로 둡니다)")
        proceed = self.ask_yes_no(APP_TITLE, confirm_msg + "\n\n" + summary)
        if not proceed:
            shutil.rmtree(work_dir, ignore_errors=True)
            self.log(f"{mod_archive.name}: 건너뜀 (사용자 취소)")
            return

        output_root = work_dir.parent / (work_dir.name + "_fixed")
        shutil.copytree(mod_root, output_root)
        stats = process_mod(mod_root, output_root, game, allow_cross_piece=True, log=self.log)
        repackage_for_fluffy(output_root, log=self.log)

        self.log(f"완료: fixed={stats['fixed']} already_current={stats['already_current']} "
                 f"skipped={stats['skipped']} errors={stats['errors']} "
                 f"texture_paths_restored={stats['textures_restored']}")

        save_dir = self.ask_save_dir(f"[{mod_archive.name}] 복구된 모드를 저장할 폴더 선택")
        if not save_dir:
            self.log(f"{mod_archive.name}: 저장 위치를 선택하지 않았습니다. 임시 폴더: {output_root}")
            return

        out_zip = Path(save_dir) / (mod_archive.stem + "_fixed.zip")
        self.log(f"압축 중: {out_zip}")
        zip_folder(output_root, out_zip)

        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(output_root, ignore_errors=True)

        self.show_info(APP_TITLE, f"[{mod_archive.name}] 복구 완료!\n\n{stats['fixed']}개 파일 복구, "
                                   f"{stats['textures_restored']}개 텍스처 경로 복원.\n\n저장 위치:\n{out_zip}")


def main():
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
