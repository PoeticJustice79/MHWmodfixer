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
    "en": "English",
    "ko": "한국어",
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
    "notice_verifying": {
        "ko": "검증 중입니다. 프로그램을 끄지 마시고 조금 더 기다려주세요.",
        "en": "Verifying -- please don't close the program, this may take a while.",
        "zh_tw": "正在驗證，請勿關閉程式，可能需要一些時間。",
        "zh_cn": "正在验证，请勿关闭程序，可能需要一些时间。",
        "ja": "検証中です。プログラムを閉じずにしばらくお待ちください。",
    },
    "progress_phase_loose_scan": {
        "ko": "개별 파일 확인 중", "en": "Checking individual files",
        "zh_tw": "正在檢查個別檔案", "zh_cn": "正在检查各个文件", "ja": "個別ファイルを確認中",
    },
    "progress_phase_pak_scan": {
        "ko": "pak 내부 항목 확인 중", "en": "Checking entries inside .pak",
        "zh_tw": "正在檢查 pak 內的項目", "zh_cn": "正在检查 pak 内的条目", "ja": "pak内のエントリを確認中",
    },
    "progress_phase_pak_resolve": {
        "ko": "도너 매칭 중", "en": "Matching against vanilla donors",
        "zh_tw": "正在比對原版供體", "zh_cn": "正在匹配原版供体", "ja": "バニラドナーと照合中",
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
    "dlg_choose_save_dir_batch": {
        "ko": "복구된 모드를 저장할 폴더 선택 (목록의 모든 모드가 이 폴더에 저장됩니다)",
        "en": "Select a folder to save repaired mods (all mods in the queue will be saved here)",
        "zh_tw": "選擇要儲存修復後模組的資料夾（清單中所有模組都會儲存於此）",
        "zh_cn": "选择要保存修复后模组的文件夹（列表中所有模组都会保存于此）",
        "ja": "修復済みMODの保存先フォルダを選択（キュー内のすべてのMODがここに保存されます）",
    },
    "msg_batch_done": {
        "ko": "복구 완료!\n\n총 {total}개 중 수정 {fixed}개, 이미 최신 {already_current}개, "
              "확인 불가 {unresolved}개, 오류 {errors}개.\n\n저장 위치:\n{out}",
        "en": "Repair complete!\n\n{fixed} fixed, {already_current} already up to date, "
              "{unresolved} couldn't be verified, {errors} error(s), out of {total} total.\n\nSaved to:\n{out}",
        "zh_tw": "修復完成！\n\n共 {total} 個，已修復 {fixed} 個、已是最新 {already_current} 個、"
                 "無法確認 {unresolved} 個、錯誤 {errors} 個。\n\n儲存位置：\n{out}",
        "zh_cn": "修复完成！\n\n共 {total} 个，已修复 {fixed} 个、已是最新 {already_current} 个、"
                 "无法确认 {unresolved} 个、错误 {errors} 个。\n\n保存位置：\n{out}",
        "ja": "修復完了！\n\n全 {total} 件中、修復 {fixed} 件、すでに最新 {already_current} 件、"
              "確認不可 {unresolved} 件、エラー {errors} 件。\n\n保存先：\n{out}",
    },
    "msg_unresolved_parts_hint": {
        "ko": "참고: {count}개 부위는 안전하게 자동 수정하지 못해 원본 그대로 남았습니다. "
              "이 부위를 착용하면 색이 이상하거나, 안 보이거나, 심하면 게임이 로딩 중 멈출 수 있습니다. "
              "\"재구성 안 되는 부위도 강제로 수정 시도\" 옵션을 켜고 다시 시도해보세요 -- "
              "단, 실험적 기능이라 결과를 게임에서 꼭 직접 확인하세요.",
        "en": "Note: {count} part(s) couldn't be safely auto-repaired and were left as the original "
              "files. Wearing that part can range from a color glitch to invisibility to the game "
              "hanging while loading. Try re-running with \"Force-fix parts that don't safely "
              "reconcile\" checked -- this is experimental, so verify the result in-game before "
              "trusting it.",
        "zh_tw": "提示：有 {count} 個部位無法安全自動修復，已保留原始檔案。穿上該部位可能出現顏色異常、"
                 "看不見，甚至讓遊戲在讀取時卡住。可以勾選「對無法安全還原的部位嘗試強制修復」後重新執行 -- "
                 "此為實驗性功能，請務必在遊戲中親自確認結果。",
        "zh_cn": "提示：有 {count} 个部位无法安全自动修复，已保留原始文件。穿上该部位可能出现颜色异常、"
                 "看不见，甚至让游戏在加载时卡住。可以勾选“对无法安全还原的部位尝试强制修复”后重新运行 -- "
                 "此为实验性功能，请务必在游戏中亲自确认结果。",
        "ja": "注意：{count} 個の部位は安全に自動修復できず、元のファイルのまま残っています。この部位を"
              "装着すると、色がおかしくなる、見えなくなる、最悪の場合ゲームがロード中に停止することがあります。"
              "「安全に一致しない部位も強制修復を試みる」にチェックを入れて再実行してみてください -- "
              "実験的な機能のため、結果は必ずゲーム内で確認してください。",
    },
    "lbl_experimental_options": {
        "ko": "⚠ 실험적 옵션",
        "en": "⚠ Experimental options",
        "zh_tw": "⚠ 實驗性選項",
        "zh_cn": "⚠ 实验性选项",
        "ja": "⚠ 実験的オプション",
    },
    "lbl_experimental_hint": {
        "ko": "결과는 반드시 게임에서 직접 확인하세요. 일부 옵션은 특정 모드에서 크래시가 확인됐습니다.",
        "en": "Always verify results in-game. Some options are confirmed to crash on certain mods.",
        "zh_tw": "請務必在遊戲中親自確認結果。部分選項已確認會在特定模組上導致遊戲崩潰。",
        "zh_cn": "请务必在游戏中亲自确认结果。部分选项已确认会在特定模组上导致游戏崩溃。",
        "ja": "結果は必ずゲーム内で確認してください。一部のオプションは特定のMODでクラッシュが確認されています。",
    },
    "chk_force_unresolved": {
        "ko": "안 고쳐진 부위 강제 수정",
        "en": "Force-fix unrepaired parts",
        "zh_tw": "強制修復未修好的部位",
        "zh_cn": "强制修复未修好的部位",
        "ja": "未修復の部位を強制修復",
    },
    "chk_preserve_extra": {
        "ko": "모드 전용 효과 보존 시도",
        "en": "Keep mod's custom effects",
        "zh_tw": "保留模組專屬效果",
        "zh_cn": "保留模组专属效果",
        "ja": "MOD専用エフェクトを保持",
    },
    "chk_shader_migration": {
        "ko": "셰이더 전환",
        "en": "Shader migration",
        "zh_tw": "著色器遷移",
        "zh_cn": "着色器迁移",
        "ja": "シェーダー移行",
    },
    "warn_single_instance": {
        "ko": "이미 실행 중입니다.", "en": "already running.",
        "zh_tw": "已經在執行中。", "zh_cn": "已经在运行中。", "ja": "はすでに実行中です。",
    },
    "summary_total_checked": {
        "ko": "총 {total}개 mdf2 확인 (loose {loose}개 + pak 내부 {pak}개)",
        "en": "{total} mdf2 file(s) checked ({loose} loose + {pak} inside paks)",
        "zh_tw": "共檢查 {total} 個 mdf2 檔案（loose {loose} 個 + pak 內 {pak} 個）",
        "zh_cn": "共检查 {total} 个 mdf2 文件（loose {loose} 个 + pak 内 {pak} 个）",
        "ja": "mdf2 ファイルを {total} 個確認（loose {loose} 個 + pak 内 {pak} 個）",
    },
    "summary_outdated_header": {
        "ko": "구조가 달라짐 (업데이트 필요): {count}개",
        "en": "Structure changed (update needed): {count}",
        "zh_tw": "結構已變更（需要更新）：{count} 個",
        "zh_cn": "结构已变更（需要更新）：{count} 个",
        "ja": "構造が変更されています（更新が必要）：{count} 個",
    },
    "summary_material_label": {
        "ko": "머티리얼: {names}", "en": "material(s): {names}",
        "zh_tw": "材質：{names}", "zh_cn": "材质：{names}", "ja": "マテリアル：{names}",
    },
    "summary_more": {
        "ko": "... 외 {count}개", "en": "... and {count} more",
        "zh_tw": "...等其他 {count} 個", "zh_cn": "...等其他 {count} 个", "ja": "...他 {count} 個",
    },
    "summary_current_header": {
        "ko": "이미 최신 구조: {count}개", "en": "Already up to date: {count}",
        "zh_tw": "已是最新結構：{count} 個", "zh_cn": "已是最新结构：{count} 个",
        "ja": "すでに最新の構造：{count} 個",
    },
    "summary_unresolved_header": {
        "ko": "안전하게 매칭 가능한 바닐라 도너를 찾지 못함: {count}개",
        "en": "No safely matchable vanilla donor found: {count}",
        "zh_tw": "找不到可安全對應的原版素材：{count} 個",
        "zh_cn": "找不到可安全对应的原版素材：{count} 个",
        "ja": "安全に一致するバニラドナーが見つかりません：{count} 個",
    },
    "pak_suffix": {
        "ko": "(pak)", "en": "(pak)", "zh_tw": "（pak）", "zh_cn": "（pak）", "ja": "（pak）",
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
    "menu_settings": {"ko": "설정", "en": "Settings"},
    "menu_dev_options": {"ko": "개발자 옵션", "en": "Developer Options"},
    "menu_rsz_snapshot": {"ko": "RSZ 스냅샷...", "en": "RSZ Snapshot..."},
    "dlg_snapshot_title": {"ko": "RSZ 스냅샷 관리", "en": "RSZ Snapshot Manager"},
    "snap_role_current": {"ko": "현재판", "en": "Current"},
    "snap_role_archived": {"ko": "보관됨", "en": "Archived"},
    "snap_not_present": {"ko": "(없음)", "en": "(not present)"},
    "snap_label": {"ko": "라벨", "en": "Label"},
    "snap_game_date": {"ko": "게임 업데이트 날짜", "en": "Game update date"},
    "snap_baked_at": {"ko": "생성 날짜", "en": "Baked at"},
    "snap_type_count": {"ko": "타입 개수", "en": "Types"},
    "dlg_choose_snapshot": {
        "ko": "스냅샷 파일 선택 (.json.gz)", "en": "Select a snapshot file (.json.gz)",
    },
    "filetype_snapshot": {"ko": "RSZ 스냅샷", "en": "RSZ snapshot"},
    "btn_import_snapshot": {"ko": "스냅샷 가져오기...", "en": "Import snapshot..."},
    "btn_close": {"ko": "닫기", "en": "Close", "zh_tw": "關閉", "zh_cn": "关闭", "ja": "閉じる"},
    "ask_snapshot_role": {
        "ko": "이 스냅샷을 \"현재판\"으로 설치할까요?\n\n예: 현재판으로 설치 (실제 검증에 사용됨, 기존 현재판은 자동으로 보관됨)\n아니오: 보관만 함 (참고용, 아직 실제 검증에는 쓰이지 않음)",
        "en": "Install this snapshot as \"current\"?\n\nYes: install as current (actually used for verification; whatever was current is automatically archived)\nNo: just archive it (reference only, not used for verification yet)",
    },
    "msg_snapshot_installed": {
        "ko": "설치 완료: {count}개 타입, 라벨 \"{label}\"",
        "en": "Installed: {count} types, label \"{label}\"",
    },
    "msg_snapshot_merge_stats": {
        "ko": "\n\n기존 레지스트리를 덮어쓰지 않고 보강했습니다: {corrected}개 타입 보정, "
              "{added}개 새 타입 추가, {shape_mismatches}개는 모양이 안 맞아 기존 값 그대로 유지.",
        "en": "\n\nMerged into the existing registry instead of overwriting it: {corrected} type(s) "
              "corrected, {added} new type(s) added, {shape_mismatches} left unchanged (shape mismatch).",
    },
    "err_snapshot_import": {
        "ko": "스냅샷을 설치하지 못했습니다:\n{e}", "en": "Couldn't install the snapshot:\n{e}",
    },
    "btn_check_github": {
        "ko": "GitHub에서 최신 데이터 확인...", "en": "Check GitHub for latest data...",
    },
    "progress_phase_downloading_rsz": {
        "ko": "RSZ 데이터 다운로드 중", "en": "Downloading RSZ data",
    },
    "ask_confirm_download": {
        "ko": "REasy 프로젝트(github.com/seifhassine/REasy)에서 최신 RSZ 타입 데이터(~100MB)를 "
              "다운로드해서 \"현재판\"으로 설치합니다. 기존 현재판은 자동으로 \"이전판\"으로 "
              "보존됩니다. 계속할까요?",
        "en": "This downloads the latest RSZ type data (~100MB) from the REasy project "
              "(github.com/seifhassine/REasy) and installs it as \"current\". The existing "
              "current snapshot is automatically kept as \"previous\". Continue?",
    },
    "msg_snapshot_verify_ok": {
        "ko": "\n\n실제 게임 파일로 검증: 통과 (이 스냅샷이 현재 설치된 게임 버전과 일치함을 확인)",
        "en": "\n\nVerified against a real game file: passed (confirmed this snapshot matches your installed game version)",
    },
    "msg_snapshot_verify_fail": {
        "ko": "\n\n⚠ 실제 게임 파일로 검증: 불일치 -- 이 스냅샷이 현재 설치된 게임 버전과 안 맞을 "
              "수 있습니다. 이전판으로 되돌리는 것을 고려하세요.",
        "en": "\n\n⚠ Verified against a real game file: MISMATCH -- this snapshot may not match "
              "your installed game version. Consider reverting to the previous snapshot.",
    },
    "msg_snapshot_verify_unknown": {
        "ko": "\n\n실제 게임 파일로 검증: 확인 불가 (검증 대상 파일 자체가 커버리지 밖이라 판단할 "
              "수 없음 -- 실패는 아님)",
        "en": "\n\nVerified against a real game file: inconclusive (the check file itself falls "
              "outside this data's coverage -- not a failure, just no confirmation either way)",
    },
    "err_download_failed": {
        "ko": "다운로드에 실패했습니다:\n{e}", "en": "Download failed:\n{e}",
    },
    "msg_partial_materials_hint": {
        "ko": "참고: {count}개 모드에서 일부 재질은 게임 안에 참고할 수 있는 바닐라 파일이 아예 없어서 "
              "고칠 수 없었고, 원본 그대로 남겨졌습니다. 같은 파일의 나머지 재질은 정상적으로 수정됐습니다. "
              "이건 강제 수정 옵션으로도 해결되지 않습니다 (참고할 대상 자체가 없기 때문).",
        "en": "Note: {count} mod(s) had one or more materials with no matching vanilla file anywhere in "
              "the game to compare against, so those specific materials were left exactly as shipped -- "
              "everything else in the same file(s) was still fixed normally. The \"force-fix\" option "
              "won't help here (there's nothing to force it against).",
    },

    # ---- 적용 방어구 변경 (armor slot retargeting) -----------------------
    "btn_retarget": {
        "ko": "적용 방어구 변경", "en": "Change Target Armor",
        "zh_tw": "更換適用防具", "zh_cn": "更换适用防具", "ja": "適用防具の変更",
    },
    "tip_retarget": {
        "ko": "모드가 원래 목표로 하는 방어구를, 물리(충돌/체인) 구성이 같은 다른 방어구로 옮겨서 "
              "적용할 수 있게 해줍니다. 예: 다른 모드와 슬롯이 겹칠 때 충돌 없는 방어구로 옮기기.\n"
              "모드 압축파일을 선택하면 현재 어떤 방어구(들)를 목표로 하는지 자동으로 인식합니다 -- "
              "모드가 방어구 여러 개에 걸쳐 있으면 각각 따로 옮기거나 그대로 둘지 정할 수 있습니다.",
        "en": "Relocates a mod from the armor it currently targets onto a different armor with a "
              "matching physics (collision/chain) setup -- e.g. to resolve a slot conflict with "
              "another mod. Pick a mod archive and this detects every armor slot it targets -- if it "
              "spans more than one, you decide per slot whether to move it or leave it as-is.",
    },
    "dlg_retarget_title": {
        "ko": "적용 방어구 변경", "en": "Change Target Armor",
        "zh_tw": "更換適用防具", "zh_cn": "更换适用防具", "ja": "適用防具の変更",
    },
    "lbl_retarget_file": {
        "ko": "모드 파일:", "en": "Mod file:", "zh_tw": "模組檔案:", "zh_cn": "模组文件:", "ja": "MODファイル:",
    },
    "btn_choose_file": {
        "ko": "선택...", "en": "Choose...", "zh_tw": "選擇...", "zh_cn": "选择...", "ja": "選択...",
    },
    "lbl_retarget_slots": {
        "ko": "감지된 방어구 슬롯", "en": "Detected armor slots",
        "zh_tw": "偵測到的防具欄位", "zh_cn": "检测到的防具栏位", "ja": "検出された防具スロット",
    },
    "lbl_retarget_targets": {
        "ko": "변경 가능한 방어구", "en": "Compatible target armor",
        "zh_tw": "可變更的防具", "zh_cn": "可变更的防具", "ja": "変更可能な防具",
    },
    "msg_retarget_no_file": {
        "ko": "이동할 모드 압축파일을 선택하세요.", "en": "Choose a mod archive to relocate.",
        "zh_tw": "請選擇要移動的模組壓縮檔。", "zh_cn": "请选择要移动的模组压缩包。",
        "ja": "移動するMODアーカイブを選択してください。",
    },
    "msg_retarget_detecting": {
        "ko": "분석 중...", "en": "Analyzing...", "zh_tw": "分析中...", "zh_cn": "分析中...", "ja": "解析中...",
    },
    "msg_retarget_multi_summary": {
        "ko": "이 모드는 방어구 슬롯 {count}개를 사용합니다 (그 외 슬롯과 무관한 파일 {unmatched}개는 "
              "손대지 않고 그대로 포함됩니다). 아래 목록에서 슬롯을 하나씩 선택해 옮길 곳을 정하거나 "
              "그대로 둘지 결정하세요 -- 전부 결정해야 파일을 생성할 수 있습니다.",
        "en": "This mod uses {count} armor slot(s) (plus {unmatched} slot-unrelated file(s), which are "
              "always kept exactly as they are). Select each slot below and either choose where to move "
              "it or leave it unchanged -- every slot needs a decision before you can generate the file.",
        "zh_tw": "此模組使用了 {count} 個防具欄位（另外 {unmatched} 個與欄位無關的檔案將原封不動保留）。"
                 "請在下方清單中逐一選擇欄位，決定要移動到哪裡或保持不變 -- 所有欄位都需要決定後才能生成檔案。",
        "zh_cn": "此模组使用了 {count} 个防具栏位（另外 {unmatched} 个与栏位无关的文件将原封不动保留）。"
                 "请在下方列表中逐一选择栏位，决定要移动到哪里或保持不变 -- 所有栏位都需要决定后才能生成文件。",
        "ja": "このMODは防具スロットを{count}個使用しています（スロットと無関係なファイル{unmatched}個は"
              "手を加えずそのまま含まれます）。下のリストからスロットを一つずつ選び、移動先を決めるか"
              "そのままにするか選んでください -- すべてのスロットを決定するまでファイルは生成できません。",
    },
    "msg_retarget_no_slot_found": {
        "ko": "이 모드에서 방어구 슬롯을 찾지 못했습니다.", "en": "No armor slot was detected in this mod.",
        "zh_tw": "在此模組中找不到防具欄位。", "zh_cn": "在此模组中找不到防具栏位。",
        "ja": "このMODには防具スロットが見つかりませんでした。",
    },
    "msg_retarget_no_targets": {
        "ko": "물리 구성이 호환되는 다른 방어구를 찾지 못했습니다.",
        "en": "No physics-compatible target armor was found.",
        "zh_tw": "找不到物理結構相容的其他防具。", "zh_cn": "找不到物理结构兼容的其他防具。",
        "ja": "物理構成が互換性のある他の防具が見つかりませんでした。",
    },
    "col_slot": {"ko": "슬롯", "en": "Slot", "zh_tw": "欄位", "zh_cn": "栏位", "ja": "スロット"},
    "col_armor": {"ko": "방어구", "en": "Armor", "zh_tw": "防具", "zh_cn": "防具", "ja": "防具"},
    "col_gender": {"ko": "성별", "en": "Gender", "zh_tw": "性別", "zh_cn": "性别", "ja": "性別"},
    "col_files": {"ko": "파일 수", "en": "Files", "zh_tw": "檔案數", "zh_cn": "文件数", "ja": "ファイル数"},
    "col_status": {"ko": "결정", "en": "Decision", "zh_tw": "決定", "zh_cn": "决定", "ja": "決定"},
    "col_compat": {"ko": "호환성", "en": "Compatibility", "zh_tw": "相容性", "zh_cn": "兼容性", "ja": "互換性"},
    "col_note": {"ko": "비고", "en": "Note", "zh_tw": "備註", "zh_cn": "备注", "ja": "備考"},
    "status_pending": {
        "ko": "결정 필요", "en": "Needs a decision",
        "zh_tw": "尚待決定", "zh_cn": "尚待决定", "ja": "決定が必要",
    },
    "status_unchanged": {
        "ko": "그대로 유지", "en": "Left unchanged",
        "zh_tw": "保持不變", "zh_cn": "保持不变", "ja": "変更なし",
    },
    "status_target": {
        "ko": "→ {name} ({slot})로 이동", "en": "→ move to {name} ({slot})",
        "zh_tw": "→ 移動至 {name}（{slot}）", "zh_cn": "→ 移动至 {name}（{slot}）",
        "ja": "→ {name}（{slot}）に移動",
    },
    "grade_exact": {
        "ko": "물리 완벽 호환", "en": "Full physics match",
        "zh_tw": "物理完全相容", "zh_cn": "物理完全兼容", "ja": "物理完全互換",
    },
    "grade_partial": {
        "ko": "일부 물리 소실", "en": "Some physics lost",
        "zh_tw": "部分物理消失", "zh_cn": "部分物理消失", "ja": "一部物理消失",
    },
    "grade_gpuc": {
        "ko": "물리 원단 주의", "en": "GPU cloth caution",
        "zh_tw": "物理布料注意", "zh_cn": "物理布料注意", "ja": "物理布注意",
    },
    "note_lost_physics": {
        "ko": "{pieces}번 부위 체인 물리 없음", "en": "no chain physics on piece(s) {pieces}",
        "zh_tw": "{pieces}號部位無鏈條物理", "zh_cn": "{pieces}号部位无链条物理",
        "ja": "{pieces}番部位にチェーン物理なし",
    },
    "note_gpuc_pieces": {
        "ko": "{pieces}번 부위 물리 원단(편집 불가)", "en": "piece(s) {pieces} has uneditable GPU cloth",
        "zh_tw": "{pieces}號部位為物理布料（無法編輯）", "zh_cn": "{pieces}号部位为物理布料（无法编辑）",
        "ja": "{pieces}番部位が物理布（編集不可）",
    },
    "btn_apply_to_slot": {
        "ko": "이 슬롯에 적용", "en": "Apply to this slot",
        "zh_tw": "套用至此欄位", "zh_cn": "应用至此栏位", "ja": "このスロットに適用",
    },
    "btn_leave_unchanged": {
        "ko": "이 슬롯은 그대로 두기", "en": "Leave this slot unchanged",
        "zh_tw": "保持此欄位不變", "zh_cn": "保持此栏位不变", "ja": "このスロットはそのままにする",
    },
    "btn_generate_retarget": {
        "ko": "이동 파일 생성", "en": "Generate Relocated File",
        "zh_tw": "生成移動後檔案", "zh_cn": "生成移动后文件", "ja": "移動ファイルを生成",
    },
    "dlg_choose_mod_archive": {
        "ko": "모드 압축파일 선택", "en": "Choose mod archive",
        "zh_tw": "選擇模組壓縮檔", "zh_cn": "选择模组压缩包", "ja": "MODアーカイブを選択",
    },
    "filetype_mod_archive": {
        "ko": "모드 압축파일", "en": "Mod archive",
        "zh_tw": "模組壓縮檔", "zh_cn": "模组压缩包", "ja": "MODアーカイブ",
    },
    "msg_retarget_select_target": {
        "ko": "목록에서 옮길 대상 방어구를 선택하세요.", "en": "Select a target armor from the list.",
        "zh_tw": "請從清單中選擇要移動的目標防具。", "zh_cn": "请从列表中选择要移动的目标防具。",
        "ja": "リストから移動先の防具を選択してください。",
    },
    "msg_retarget_pick_slot_first": {
        "ko": "먼저 위 목록에서 슬롯을 선택하세요.", "en": "Select a slot from the list above first.",
        "zh_tw": "請先在上方清單中選擇欄位。", "zh_cn": "请先在上方列表中选择栏位。",
        "ja": "先に上のリストからスロットを選択してください。",
    },
    "msg_retarget_incomplete": {
        "ko": "아직 결정하지 않은 슬롯이 있습니다. 모든 슬롯에 대해 이동할 곳을 정하거나 "
              "그대로 두기를 선택해야 합니다.",
        "en": "Some detected slots still need a decision. Every slot must be either assigned a target "
              "or explicitly left unchanged before generating.",
        "zh_tw": "還有欄位尚未決定。每個欄位都必須指定移動目標，或明確選擇保持不變，才能生成檔案。",
        "zh_cn": "还有栏位尚未决定。每个栏位都必须指定移动目标，或明确选择保持不变，才能生成文件。",
        "ja": "まだ決定していないスロットがあります。生成する前に、すべてのスロットについて"
              "移動先を指定するか、明示的にそのままにするかを選んでください。",
    },
    "err_no_game_dir": {
        "ko": "먼저 유효한 게임 폴더를 지정해야 합니다.", "en": "A valid game folder must be set first.",
        "zh_tw": "請先指定有效的遊戲資料夾。", "zh_cn": "请先指定有效的游戏文件夹。",
        "ja": "先に有効なゲームフォルダを指定してください。",
    },
    "ask_retarget_unverified": {
        "ko": "다음 이동에서 일부 파일을 현재 게임에서 확인하지 못했습니다:\n{missing}\n"
              "그래도 계속 진행할까요?",
        "en": "Some files for the following move(s) could not be verified against the current game:\n"
              "{missing}\nContinue anyway?",
        "zh_tw": "以下移動的部分檔案無法在目前的遊戲中確認:\n{missing}\n仍要繼續嗎？",
        "zh_cn": "以下移动的部分文件无法在当前游戏中确认:\n{missing}\n仍要继续吗？",
        "ja": "次の移動で一部のファイルが現在のゲームで確認できませんでした:\n{missing}\n"
              "それでも続行しますか？",
    },
    "dlg_save_retarget": {
        "ko": "이동된 모드 파일 저장", "en": "Save relocated mod file",
        "zh_tw": "儲存移動後的模組檔案", "zh_cn": "保存移动后的模组文件", "ja": "移動後のMODファイルを保存",
    },
    "filetype_zip": {"ko": "ZIP 파일", "en": "ZIP file", "zh_tw": "ZIP 檔案", "zh_cn": "ZIP 文件", "ja": "ZIPファイル"},
    "msg_retarget_generating": {
        "ko": "생성 중...", "en": "Generating...", "zh_tw": "生成中...", "zh_cn": "生成中...", "ja": "生成中...",
    },
    "msg_retarget_done": {
        "ko": "저장했습니다 ({moved}개 슬롯 이동, {kept}개 슬롯 그대로 유지):\n{path}",
        "en": "Saved ({moved} slot(s) moved, {kept} slot(s) left unchanged):\n{path}",
        "zh_tw": "已儲存（{moved} 個欄位已移動，{kept} 個欄位保持不變）:\n{path}",
        "zh_cn": "已保存（{moved} 个栏位已移动，{kept} 个栏位保持不变）:\n{path}",
        "ja": "保存しました（{moved}個のスロットを移動、{kept}個のスロットはそのまま）:\n{path}",
    },
}

_current_lang = "en"


def load_saved_language() -> str:
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        lang = data.get("language")
        if lang in LANGUAGES:
            return lang
    except (OSError, ValueError):
        pass
    return "en"


def save_language(lang: str) -> None:
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps({"language": lang}), encoding="utf-8")
    except OSError:
        pass


def set_language(lang: str) -> None:
    global _current_lang
    _current_lang = lang if lang in LANGUAGES else "en"


def get_language() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    template = entry.get(_current_lang) or entry.get("en") or entry.get("ko") or key
    return template.format(**kwargs) if kwargs else template
