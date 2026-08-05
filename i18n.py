"""
GUI-chrome localization only (window labels/buttons/status text/dialog
boxes) -- deliberately NOT the detailed processing log emitted during a
repair run (donor-matching, staleness diagnosis, etc. from auto_fix.py /
pak_mod_fix.py / slot_merge.py / pfb_fix.py / fluffy_repackage.py), which
stays as its existing Korean/English technical text regardless of the
selected UI language. Translating that too would be a much larger,
lower-value effort (dozens of scattered f-strings full of format-specific
jargon); the GUI chrome is what a non-technical user actually needs
localized to use the tool at all.

Usage: call set_language("en") (etc.) once at startup (after loading the
saved preference) and again whenever the user changes it; call t("key",
**kwargs) anywhere a translated string is needed -- kwargs are applied via
str.format() against the selected language's template.
"""
from __future__ import annotations

import json
from pathlib import Path

LANGUAGES = {
    "ko": "한국어",
    "en": "English",
    "zh_tw": "繁體中文",
    "zh_cn": "简体中文",
    "ja": "日本語",
}

_SETTINGS_PATH = Path.home() / "AppData" / "Local" / "MHWmodfixer" / "settings.json"

_STRINGS = {
    "lbl_game_dir": {
        "ko": "게임 폴더:", "en": "Game folder:", "zh_tw": "遊戲資料夾:",
        "zh_cn": "游戏文件夹:", "ja": "ゲームフォルダ:",
    },
    "btn_browse_game": {
        "ko": "변경", "en": "Change", "zh_tw": "變更", "zh_cn": "更改", "ja": "変更",
    },
    "lbl_lang": {
        "ko": "언어:", "en": "Language:", "zh_tw": "語言:", "zh_cn": "语言:", "ja": "言語:",
    },
    "lbl_mod_list": {
        "ko": "모드 압축파일 목록 (여기로 끌어다 놓기 가능):",
        "en": "Mod archive list (drag & drop here):",
        "zh_tw": "模組壓縮檔清單（可拖放至此）：",
        "zh_cn": "模组压缩包列表（可拖放至此）：",
        "ja": "MODアーカイブ一覧（ここにドラッグ＆ドロップ可能）：",
    },
    "btn_add_mod": {
        "ko": "추가 (zip/7z/rar)", "en": "Add (zip/7z/rar)", "zh_tw": "新增 (zip/7z/rar)",
        "zh_cn": "添加 (zip/7z/rar)", "ja": "追加 (zip/7z/rar)",
    },
    "btn_remove_selected": {
        "ko": "선택 제거", "en": "Remove Selected", "zh_tw": "移除選取項目",
        "zh_cn": "移除选中项", "ja": "選択を削除",
    },
    "btn_clear_all": {
        "ko": "전체 지우기", "en": "Clear All", "zh_tw": "全部清除",
        "zh_cn": "全部清除", "ja": "すべてクリア",
    },
    "btn_start": {
        "ko": "복구 시작", "en": "Start Repair", "zh_tw": "開始修復",
        "zh_cn": "开始修复", "ja": "修復開始",
    },
    "btn_open_log_folder": {
        "ko": "로그 폴더 열기", "en": "Open Log Folder", "zh_tw": "開啟記錄檔資料夾",
        "zh_cn": "打开日志文件夹", "ja": "ログフォルダを開く",
    },
    "status_default": {
        "ko": "모드 압축파일을 끌어다 놓거나 선택하세요",
        "en": "Drag & drop a mod archive, or select one",
        "zh_tw": "請拖放或選擇模組壓縮檔",
        "zh_cn": "请拖放或选择模组压缩包",
        "ja": "MODアーカイブをドラッグ＆ドロップまたは選択してください",
    },
    "status_indexing": {
        "ko": "게임 파일 인덱싱 중...", "en": "Indexing game files...",
        "zh_tw": "正在索引遊戲檔案...", "zh_cn": "正在索引游戏文件...",
        "ja": "ゲームファイルをインデックス中...",
    },
    "status_processing": {
        "ko": "처리 중 ({i}/{total}): {name}", "en": "Processing ({i}/{total}): {name}",
        "zh_tw": "處理中 ({i}/{total})：{name}", "zh_cn": "处理中 ({i}/{total})：{name}",
        "ja": "処理中 ({i}/{total})：{name}",
    },
    "status_done": {
        "ko": "완료 -- 목록을 정리하거나 새 모드를 추가하세요",
        "en": "Done -- clear the list or add new mods",
        "zh_tw": "完成 -- 請清理清單或新增模組",
        "zh_cn": "完成 -- 请清理列表或添加新模组",
        "ja": "完了 -- リストを整理するか新しいMODを追加してください",
    },
    "dlg_choose_game_dir": {
        "ko": "Monster Hunter Wilds 설치 폴더 선택",
        "en": "Select Monster Hunter Wilds install folder",
        "zh_tw": "選擇《魔物獵人 Wilds》安裝資料夾",
        "zh_cn": "选择《怪物猎人 Wilds》安装文件夹",
        "ja": "モンスターハンターワイルズのインストールフォルダを選択",
    },
    "dlg_choose_mod": {
        "ko": "모드 압축파일 선택 (여러 개 선택 가능)",
        "en": "Select mod archive(s) (multiple allowed)",
        "zh_tw": "選擇模組壓縮檔（可多選）",
        "zh_cn": "选择模组压缩包（可多选）",
        "ja": "MODアーカイブを選択（複数選択可）",
    },
    "filetype_archives": {
        "ko": "압축파일", "en": "Archives", "zh_tw": "壓縮檔", "zh_cn": "压缩包", "ja": "アーカイブ",
    },
    "filetype_allfiles": {
        "ko": "모든 파일", "en": "All files", "zh_tw": "所有檔案", "zh_cn": "所有文件", "ja": "すべてのファイル",
    },
    "warn_no_mod": {
        "ko": "모드 압축파일을 먼저 추가하세요.", "en": "Please add a mod archive first.",
        "zh_tw": "請先新增模組壓縮檔。", "zh_cn": "请先添加模组压缩包。",
        "ja": "先にMODアーカイブを追加してください。",
    },
    "warn_bad_game_dir": {
        "ko": "게임 폴더 경로가 올바르지 않습니다.", "en": "The game folder path is invalid.",
        "zh_tw": "遊戲資料夾路徑無效。", "zh_cn": "游戏文件夹路径无效。",
        "ja": "ゲームフォルダのパスが正しくありません。",
    },
    "err_unhandled": {
        "ko": "오류가 발생했습니다:\n{e}", "en": "An error occurred:\n{e}",
        "zh_tw": "發生錯誤：\n{e}", "zh_cn": "发生错误：\n{e}", "ja": "エラーが発生しました：\n{e}",
    },
    "err_processing_mod": {
        "ko": "{name} 처리 중 오류:\n{e}", "en": "Error while processing {name}:\n{e}",
        "zh_tw": "處理 {name} 時發生錯誤：\n{e}", "zh_cn": "处理 {name} 时发生错误：\n{e}",
        "ja": "{name} の処理中にエラーが発生しました：\n{e}",
    },
    "msg_already_latest": {
        "ko": "[{name}] 이미 최신 버전입니다. 고칠 게 없습니다.\n\n{summary}",
        "en": "[{name}] Already up to date. Nothing to fix.\n\n{summary}",
        "zh_tw": "[{name}] 已是最新版本，無需修復。\n\n{summary}",
        "zh_cn": "[{name}] 已是最新版本，无需修复。\n\n{summary}",
        "ja": "[{name}] すでに最新の状態です。修復の必要はありません。\n\n{summary}",
    },
    "msg_cannot_verify": {
        "ko": "[{name}] 자동으로 안전하게 복구할 수 있는 부분이 없습니다.\n\n"
              "{count}개 파일(또는 그 안의 일부 머티리얼)에서 안전하게 매칭되는 "
              "바닐라 도너를 찾지 못해, 이미 최신인지조차 확인할 수 없습니다. "
              "이 모드는 그대로 두었습니다.\n\n{summary}",
        "en": "[{name}] Nothing could be safely auto-repaired.\n\n"
              "{count} file(s) (or some materials within them) couldn't be safely matched "
              "against a vanilla donor, so it's not even possible to tell whether they're "
              "already up to date. This mod was left untouched.\n\n{summary}",
        "zh_tw": "[{name}] 沒有可以安全自動修復的部分。\n\n"
                 "{count} 個檔案（或其中部分材質）找不到可安全對應的原版素材，"
                 "因此無法確認是否已是最新版本。此模組維持原狀未變更。\n\n{summary}",
        "zh_cn": "[{name}] 没有可以安全自动修复的部分。\n\n"
                 "{count} 个文件（或其中部分材质）找不到可安全对应的原版素材，"
                 "因此无法确认是否已是最新版本。该模组保持原状未变更。\n\n{summary}",
        "ja": "[{name}] 安全に自動修復できる箇所がありません。\n\n"
              "{count} 個のファイル（またはその中の一部マテリアル）で安全に一致する"
              "バニラドナーが見つからず、最新かどうかの確認すらできません。"
              "このMODはそのままにしました。\n\n{summary}",
    },
    "confirm_needs_fix": {
        "ko": "[{name}]\n{count}개 파일이 구버전입니다. 업데이트를 진행할까요?",
        "en": "[{name}]\n{count} file(s) are outdated. Proceed with the update?",
        "zh_tw": "[{name}]\n{count} 個檔案為舊版本，是否要進行更新？",
        "zh_cn": "[{name}]\n{count} 个文件为旧版本，是否要进行更新？",
        "ja": "[{name}]\n{count} 個のファイルが古いバージョンです。更新を進めますか？",
    },
    "confirm_unresolved_note": {
        "ko": "\n(참고: {count}개는 도너를 찾지 못해 확인이 안 되어 그대로 둡니다)",
        "en": "\n(Note: {count} couldn't be verified due to no donor match, and will be left as-is)",
        "zh_tw": "\n（附註：{count} 個因找不到對應素材而無法確認，將維持原狀）",
        "zh_cn": "\n（附注：{count} 个因找不到对应素材而无法确认，将保持原状）",
        "ja": "\n（注：{count} 個はドナーが見つからず確認できないため、そのままにします）",
    },
    "dlg_choose_save_dir": {
        "ko": "[{name}] 복구된 모드를 저장할 폴더 선택",
        "en": "[{name}] Select a folder to save the repaired mod",
        "zh_tw": "[{name}] 選擇要儲存修復後模組的資料夾",
        "zh_cn": "[{name}] 选择要保存修复后模组的文件夹",
        "ja": "[{name}] 修復済みMODの保存先フォルダを選択",
    },
    "msg_repair_done": {
        "ko": "[{name}] 복구 완료!\n\n{fixed}개 파일 복구, {restored}개 텍스처 경로 복원.\n\n저장 위치:\n{out}",
        "en": "[{name}] Repair complete!\n\n{fixed} file(s) fixed, {restored} texture path(s) restored.\n\nSaved to:\n{out}",
        "zh_tw": "[{name}] 修復完成！\n\n已修復 {fixed} 個檔案，還原 {restored} 個材質路徑。\n\n儲存位置：\n{out}",
        "zh_cn": "[{name}] 修复完成！\n\n已修复 {fixed} 个文件，还原 {restored} 个材质路径。\n\n保存位置：\n{out}",
        "ja": "[{name}] 修復完了！\n\n{fixed} 個のファイルを修復、{restored} 個のテクスチャパスを復元。\n\n保存先：\n{out}",
    },
    "warn_single_instance": {
        "ko": "이미 실행 중입니다.", "en": "already running.",
        "zh_tw": "已經在執行中。", "zh_cn": "已经在运行中。", "ja": "はすでに実行中です。",
    },
    "warn_non_ascii_path": {
        "ko": "프로그램이 설치된 경로에 한글 등 특수 문자가 포함되어 있습니다:\n\n{path}\n\n"
              "이런 경로에서는 일부 도구(압축 해제 등)가 오작동할 수 있습니다. "
              "가능하면 영문/숫자로만 이루어진 경로(예: C:\\MHWmodfixer)로 옮겨서 사용해 주세요.",
        "en": "The program's install path contains non-English characters:\n\n{path}\n\n"
              "Some bundled tools (archive extraction, etc.) may misbehave in such paths. "
              "If possible, move it to a path using only English letters/numbers "
              "(e.g. C:\\MHWmodfixer).",
        "zh_tw": "程式安裝路徑中包含非英文字元：\n\n{path}\n\n"
                 "部分內建工具（解壓縮等）在這類路徑下可能無法正常運作。"
                 "請盡量移動到僅由英文字母與數字組成的路徑（例如 C:\\MHWmodfixer）。",
        "zh_cn": "程序安装路径中包含非英文字符：\n\n{path}\n\n"
                 "部分内置工具（解压缩等）在这类路径下可能无法正常运行。"
                 "请尽量移动到仅由英文字母与数字组成的路径（例如 C:\\MHWmodfixer）。",
        "ja": "プログラムのインストールパスに日本語などの特殊文字が含まれています：\n\n{path}\n\n"
              "このようなパスでは一部のツール（アーカイブ展開など）が正しく動作しないことがあります。"
              "できるだけ英数字のみのパス（例：C:\\MHWmodfixer）に移動してご利用ください。",
    },
}

_current_lang = "ko"


def load_saved_language() -> str:
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        lang = data.get("language")
        if lang in LANGUAGES:
            return lang
    except (OSError, ValueError):
        pass
    return "ko"


def save_language(lang: str) -> None:
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps({"language": lang}), encoding="utf-8")
    except OSError:
        pass


def set_language(lang: str) -> None:
    global _current_lang
    _current_lang = lang if lang in LANGUAGES else "ko"


def get_language() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    template = entry.get(_current_lang) or entry.get("ko") or key
    return template.format(**kwargs) if kwargs else template
