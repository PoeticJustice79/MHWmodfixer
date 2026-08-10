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
    "tip_force_unresolved": {
        "ko": "로그에 '고치지 못함(unresolved)'으로 남은 부위가 있을 때 사용하세요. 안전하게 확실히 "
              "일치하는 대체품을 못 찾아 건너뛴 부위도 강제로 대체를 시도합니다.\n"
              "실험적 기능이라 색상이 어긋나거나 특정 모드에서 크래시가 날 수 있으니, 켜고 다시 돌린 "
              "뒤 반드시 게임에서 직접 확인하세요.",
        "en": "Use this when the log shows parts left unresolved -- ones where a confirmed safe "
              "match couldn't be found, so they were skipped. This forces a substitution attempt "
              "on those parts anyway.\n"
              "Experimental: can cause color mismatches or crashes on certain mods, so always "
              "verify in-game after re-running with it on.",
        "zh_tw": "當日誌顯示有部位「未修復（unresolved）」時使用。這類部位原本因為找不到確定安全的替代"
                 "品而被略過，開啟後會強制嘗試替換。\n"
                 "屬於實驗性功能，可能導致顏色錯位或在特定模組上崩潰，開啟後重新執行，請務必在遊戲中"
                 "親自確認結果。",
        "zh_cn": "当日志显示有部位「未修复（unresolved）」时使用。这类部位原本因为找不到确定安全的替代"
                 "品而被跳过，开启后会强制尝试替换。\n"
                 "属于实验性功能，可能导致颜色错位或在特定模组上崩溃，开启后重新运行，请务必在游戏中"
                 "亲自确认结果。",
        "ja": "ログに「未修復(unresolved)」のまま残った部位がある場合に使用してください。安全に一致"
              "する代替品が見つからず、スキップされた部位にも強制的に置き換えを試みます。\n"
              "実験的な機能のため、色がずれたり特定のMODでクラッシュすることがあります。オンにして"
              "再実行した後は、必ずゲーム内で結果を確認してください。",
    },
    "tip_preserve_extra": {
        "ko": "모드가 게임 기본값에 없는 자기만의 물리 효과(예: 커스텀 헤어/체인 물리)를 추가로 갖고 "
              "있을 때, 수정 과정에서 그 부분을 지우지 않고 최대한 살려보려 시도합니다.\n"
              "다만 그게 실제 커스텀 효과가 아니라 예전 게임 버전의 낡은 잔재 데이터일 수도 있어서, "
              "오히려 이 옵션 때문에 이상해지거나 크래시가 난 사례도 확인됐습니다 (예: Banshee 모드는 "
              "이 옵션을 끄는 쪽이 정답이었음). 켜고 끄고 둘 다 게임에서 비교해보는 걸 추천합니다.",
        "en": "Use this when a mod includes its own extra physics (e.g. custom hair/chain physics) "
              "beyond the game's defaults -- it tries to keep that extra data instead of "
              "discarding it during the repair.\n"
              "But that \"extra\" data can also just be stale leftovers from an older game "
              "version, not real customization -- confirmed to cause crashes/glitches on some "
              "mods when left on (e.g. the Banshee mod actually needed it OFF). Try comparing "
              "both on and off in-game.",
        "zh_tw": "當模組帶有遊戲預設沒有的自訂物理效果（例如自訂頭髮/鏈條物理）時使用，修復時會嘗試"
                 "保留這部分，而不是直接捨棄。\n"
                 "但這些「額外」資料也可能只是舊版遊戲留下的過時殘留，並非真正的自訂效果 -- 已確認"
                 "開啟此選項會讓部分模組崩潰或跑版（例如 Banshee 模組其實需要關閉此選項才正常）。建議"
                 "開關都在遊戲中比較看看。",
        "zh_cn": "当模组带有游戏默认没有的自定义物理效果（例如自定义头发/链条物理）时使用，修复时会"
                 "尝试保留这部分，而不是直接丢弃。\n"
                 "但这些「额外」数据也可能只是旧版游戏留下的过时残留，并非真正的自定义效果 -- 已确认"
                 "开启此选项会导致部分模组崩溃或错位（例如 Banshee 模组其实需要关闭此选项才正常）。建议"
                 "开关都在游戏中比较看看。",
        "ja": "MODがゲーム標準にはない独自の物理効果(カスタムヘア/チェーン物理など)を持っている場合に"
              "使用してください。修復時にその部分を削除せず、できる限り保持しようとします。\n"
              "ただし、その「追加」データが実は古いゲームバージョンの残骸データに過ぎない場合もあり、"
              "このオプションが原因で見た目がおかしくなったりクラッシュした事例も確認されています(例: "
              "Bansheeというmodはこのオプションを切る方が正解でした)。オン/オフ両方をゲーム内で比較"
              "することをおすすめします。",
    },
    "tip_shader_migration": {
        "ko": "일부 모드가 쓰는 셰이더(모피용 Base_Equip_Fur 등)가 최신 게임에서는 사실상 퇴역해서, "
              "그냥 비슷한 다른 셰이더를 대체품으로 쓰면 질감이 안 맞을 수 있습니다. 이 옵션은 그런 "
              "재질을 게임에서 실제로 검증된 진짜 후속 셰이더로 다시 빌드합니다.\n"
              "해당 셰이더를 쓰지 않는 모드에는 아무 효과가 없으니, 모피 관련 모드가 이상해 보일 때만 "
              "켜서 시도해보세요.",
        "en": "Some mods use a shader (like the Base_Equip_Fur fur shader) that's effectively "
              "retired in the current game -- substituting a plain similar-shader donor can look "
              "wrong. This rebuilds that material under its real, in-game-verified successor "
              "shader instead.\n"
              "Has no effect on mods that don't use that shader -- only try it if a fur-related "
              "mod looks off after a normal repair.",
        "zh_tw": "部分模組使用的著色器（如毛皮著色器 Base_Equip_Fur）在目前遊戲版本中實際上已被淘汰，"
                 "直接用外觀相近的著色器替代可能導致質感不對。此選項會將該材質改用遊戲中實際驗證過的"
                 "真正後繼著色器重新建構。\n"
                 "若模組沒有用到該著色器則完全不受影響 -- 只有在毛皮相關模組修復後看起來不對勁時才"
                 "需要開啟嘗試。",
        "zh_cn": "部分模组使用的着色器（如毛皮着色器 Base_Equip_Fur）在当前游戏版本中实际上已被淘汰，"
                 "直接用外观相近的着色器替代可能导致质感不对。此选项会将该材质改用游戏中实际验证过的"
                 "真正后继着色器重新构建。\n"
                 "若模组没有用到该着色器则完全不受影响 -- 只有在毛皮相关模组修复后看起来不对劲时才"
                 "需要开启尝试。",
        "ja": "一部のMODが使用しているシェーダー(毛皮用シェーダーBase_Equip_Furなど)は、現在のゲームで"
              "は事実上廃止されており、単純に似た別シェーダーで代用すると質感が合わないことがあります。"
              "このオプションは、そのマテリアルをゲーム内で実際に確認された本当の後継シェーダーで"
              "再構築します。\n"
              "該当シェーダーを使っていないMODには影響しません -- 毛皮関連のMODを修復した見た目が"
              "おかしいと感じたときだけ試してみてください。",
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
    "menu_settings": {
        "ko": "설정", "en": "Settings", "zh_tw": "設定", "zh_cn": "设置", "ja": "設定",
    },
    "menu_dev_options": {
        "ko": "개발자 옵션", "en": "Developer Options",
        "zh_tw": "開發者選項", "zh_cn": "开发者选项", "ja": "開発者オプション",
    },
    "menu_rsz_snapshot": {
        "ko": "RSZ 스냅샷...", "en": "RSZ Snapshot...",
        "zh_tw": "RSZ 快照...", "zh_cn": "RSZ 快照...", "ja": "RSZスナップショット...",
    },
    "dlg_snapshot_title": {
        "ko": "RSZ 스냅샷 관리", "en": "RSZ Snapshot Manager",
        "zh_tw": "RSZ 快照管理", "zh_cn": "RSZ 快照管理", "ja": "RSZスナップショット管理",
    },
    "snap_role_current": {
        "ko": "현재판", "en": "Current", "zh_tw": "目前版本", "zh_cn": "当前版本", "ja": "現行版",
    },
    "snap_role_archived": {
        "ko": "보관됨", "en": "Archived", "zh_tw": "已封存", "zh_cn": "已归档", "ja": "アーカイブ済み",
    },
    "snap_not_present": {
        "ko": "(없음)", "en": "(not present)", "zh_tw": "（不存在）", "zh_cn": "（不存在）", "ja": "（なし）",
    },
    "snap_label": {"ko": "라벨", "en": "Label", "zh_tw": "標籤", "zh_cn": "标签", "ja": "ラベル"},
    "snap_game_date": {
        "ko": "게임 업데이트 날짜", "en": "Game update date",
        "zh_tw": "遊戲更新日期", "zh_cn": "游戏更新日期", "ja": "ゲームアップデート日",
    },
    "snap_baked_at": {
        "ko": "생성 날짜", "en": "Baked at", "zh_tw": "生成日期", "zh_cn": "生成日期", "ja": "作成日",
    },
    "snap_type_count": {
        "ko": "타입 개수", "en": "Types", "zh_tw": "類型數量", "zh_cn": "类型数量", "ja": "タイプ数",
    },
    "dlg_choose_snapshot": {
        "ko": "스냅샷 파일 선택 (.json.gz)", "en": "Select a snapshot file (.json.gz)",
        "zh_tw": "選擇快照檔案（.json.gz）", "zh_cn": "选择快照文件（.json.gz）",
        "ja": "スナップショットファイルを選択（.json.gz）",
    },
    "filetype_snapshot": {
        "ko": "RSZ 스냅샷", "en": "RSZ snapshot",
        "zh_tw": "RSZ 快照", "zh_cn": "RSZ 快照", "ja": "RSZスナップショット",
    },
    "btn_import_snapshot": {
        "ko": "스냅샷 가져오기...", "en": "Import snapshot...",
        "zh_tw": "匯入快照...", "zh_cn": "导入快照...", "ja": "スナップショットを読み込み...",
    },
    "btn_close": {"ko": "닫기", "en": "Close", "zh_tw": "關閉", "zh_cn": "关闭", "ja": "閉じる"},
    "ask_snapshot_role": {
        "ko": "이 스냅샷을 \"현재판\"으로 설치할까요?\n\n예: 현재판으로 설치 (실제 검증에 사용됨, 기존 현재판은 자동으로 보관됨)\n아니오: 보관만 함 (참고용, 아직 실제 검증에는 쓰이지 않음)",
        "en": "Install this snapshot as \"current\"?\n\nYes: install as current (actually used for verification; whatever was current is automatically archived)\nNo: just archive it (reference only, not used for verification yet)",
        "zh_tw": "要將此快照安裝為「目前版本」嗎？\n\n是：安裝為目前版本（實際用於驗證，現有的目前版本會自動封存）\n否：僅封存（僅供參考，尚不用於驗證）",
        "zh_cn": "要将此快照安装为「当前版本」吗？\n\n是：安装为当前版本（实际用于验证，现有的当前版本会自动归档）\n否：仅归档（仅供参考，尚不用于验证）",
        "ja": "このスナップショットを「現行版」としてインストールしますか？\n\nはい：現行版としてインストール（実際の検証に使用され、既存の現行版は自動的にアーカイブされます）\nいいえ：アーカイブのみ（参考用、まだ検証には使用されません）",
    },
    "msg_snapshot_installed": {
        "ko": "설치 완료: {count}개 타입, 라벨 \"{label}\"",
        "en": "Installed: {count} types, label \"{label}\"",
        "zh_tw": "安裝完成：{count} 個類型，標籤「{label}」",
        "zh_cn": "安装完成：{count} 个类型，标签「{label}」",
        "ja": "インストール完了：{count}タイプ、ラベル「{label}」",
    },
    "msg_snapshot_merge_stats": {
        "ko": "\n\n기존 레지스트리를 덮어쓰지 않고 보강했습니다: {corrected}개 타입 보정, "
              "{added}개 새 타입 추가, {shape_mismatches}개는 모양이 안 맞아 기존 값 그대로 유지.",
        "en": "\n\nMerged into the existing registry instead of overwriting it: {corrected} type(s) "
              "corrected, {added} new type(s) added, {shape_mismatches} left unchanged (shape mismatch).",
        "zh_tw": "\n\n已合併至現有登錄檔而非覆寫：修正 {corrected} 個類型，新增 {added} 個新類型，"
                 "{shape_mismatches} 個因結構不符而保持原值。",
        "zh_cn": "\n\n已合并至现有注册表而非覆写：修正 {corrected} 个类型，新增 {added} 个新类型，"
                 "{shape_mismatches} 个因结构不符而保持原值。",
        "ja": "\n\n既存のレジストリを上書きせずマージしました：{corrected}タイプ補正、"
              "{added}個の新規タイプ追加、{shape_mismatches}個は形状不一致のため変更なし。",
    },
    "err_snapshot_import": {
        "ko": "스냅샷을 설치하지 못했습니다:\n{e}", "en": "Couldn't install the snapshot:\n{e}",
        "zh_tw": "無法安裝快照：\n{e}", "zh_cn": "无法安装快照：\n{e}", "ja": "スナップショットをインストールできませんでした：\n{e}",
    },
    "btn_check_github": {
        "ko": "GitHub에서 최신 데이터 확인...", "en": "Check GitHub for latest data...",
        "zh_tw": "從 GitHub 檢查最新資料...", "zh_cn": "从 GitHub 检查最新数据...",
        "ja": "GitHubで最新データを確認...",
    },
    "progress_phase_downloading_rsz": {
        "ko": "RSZ 데이터 다운로드 중", "en": "Downloading RSZ data",
        "zh_tw": "正在下載 RSZ 資料", "zh_cn": "正在下载 RSZ 数据", "ja": "RSZデータをダウンロード中",
    },
    "ask_confirm_download": {
        "ko": "REasy 프로젝트(github.com/seifhassine/REasy)에서 최신 RSZ 타입 데이터(~100MB)를 "
              "다운로드해서 \"현재판\"으로 설치합니다. 기존 현재판은 자동으로 \"이전판\"으로 "
              "보존됩니다. 계속할까요?",
        "en": "This downloads the latest RSZ type data (~100MB) from the REasy project "
              "(github.com/seifhassine/REasy) and installs it as \"current\". The existing "
              "current snapshot is automatically kept as \"previous\". Continue?",
        "zh_tw": "這將從 REasy 專案（github.com/seifhassine/REasy）下載最新的 RSZ 類型資料"
                 "（約 100MB）並安裝為「目前版本」。現有的目前版本會自動保留為「前一版」。要繼續嗎？",
        "zh_cn": "这将从 REasy 项目（github.com/seifhassine/REasy）下载最新的 RSZ 类型数据"
                 "（约 100MB）并安装为「当前版本」。现有的当前版本会自动保留为「上一版」。要继续吗？",
        "ja": "REasyプロジェクト（github.com/seifhassine/REasy）から最新のRSZタイプデータ"
              "（約100MB）をダウンロードし、「現行版」としてインストールします。既存の現行版は"
              "自動的に「前版」として保存されます。続行しますか？",
    },
    "msg_snapshot_verify_ok": {
        "ko": "\n\n실제 게임 파일로 검증: 통과 (이 스냅샷이 현재 설치된 게임 버전과 일치함을 확인)",
        "en": "\n\nVerified against a real game file: passed (confirmed this snapshot matches your installed game version)",
        "zh_tw": "\n\n以實際遊戲檔案驗證：通過（已確認此快照與目前安裝的遊戲版本相符）",
        "zh_cn": "\n\n以实际游戏文件验证：通过（已确认此快照与当前安装的游戏版本相符）",
        "ja": "\n\n実際のゲームファイルで検証：合格（このスナップショットが現在インストールされている"
              "ゲームバージョンと一致することを確認）",
    },
    "msg_snapshot_verify_fail": {
        "ko": "\n\n⚠ 실제 게임 파일로 검증: 불일치 -- 이 스냅샷이 현재 설치된 게임 버전과 안 맞을 "
              "수 있습니다. 이전판으로 되돌리는 것을 고려하세요.",
        "en": "\n\n⚠ Verified against a real game file: MISMATCH -- this snapshot may not match "
              "your installed game version. Consider reverting to the previous snapshot.",
        "zh_tw": "\n\n⚠ 以實際遊戲檔案驗證：不相符 -- 此快照可能與目前安裝的遊戲版本不符。"
                 "請考慮還原至前一版。",
        "zh_cn": "\n\n⚠ 以实际游戏文件验证：不相符 -- 此快照可能与当前安装的游戏版本不符。"
                 "请考虑还原至上一版。",
        "ja": "\n\n⚠ 実際のゲームファイルで検証：不一致 -- このスナップショットは現在インストール"
              "されているゲームバージョンと一致しない可能性があります。前版に戻すことを検討してください。",
    },
    "msg_snapshot_verify_unknown": {
        "ko": "\n\n실제 게임 파일로 검증: 확인 불가 (검증 대상 파일 자체가 커버리지 밖이라 판단할 "
              "수 없음 -- 실패는 아님)",
        "en": "\n\nVerified against a real game file: inconclusive (the check file itself falls "
              "outside this data's coverage -- not a failure, just no confirmation either way)",
        "zh_tw": "\n\n以實際遊戲檔案驗證：無法確認（驗證用檔案本身超出此資料的涵蓋範圍 -- 並非失敗，"
                 "只是無法確認）",
        "zh_cn": "\n\n以实际游戏文件验证：无法确认（验证用文件本身超出此数据的覆盖范围 -- 并非失败，"
                 "只是无法确认）",
        "ja": "\n\n実際のゲームファイルで検証：判定不可（検証対象のファイル自体がこのデータの"
              "カバー範囲外 -- 失敗ではなく、単に確認できないだけ）",
    },
    "err_download_failed": {
        "ko": "다운로드에 실패했습니다:\n{e}", "en": "Download failed:\n{e}",
        "zh_tw": "下載失敗：\n{e}", "zh_cn": "下载失败：\n{e}", "ja": "ダウンロードに失敗しました：\n{e}",
    },
    "msg_partial_materials_hint": {
        "ko": "참고: {count}개 모드에서 일부 재질은 게임 안에 참고할 수 있는 바닐라 파일이 아예 없어서 "
              "고칠 수 없었고, 원본 그대로 남겨졌습니다. 같은 파일의 나머지 재질은 정상적으로 수정됐습니다. "
              "이건 강제 수정 옵션으로도 해결되지 않습니다 (참고할 대상 자체가 없기 때문).",
        "en": "Note: {count} mod(s) had one or more materials with no matching vanilla file anywhere in "
              "the game to compare against, so those specific materials were left exactly as shipped -- "
              "everything else in the same file(s) was still fixed normally. The \"force-fix\" option "
              "won't help here (there's nothing to force it against).",
        "zh_tw": "備註：{count} 個模組中，部分材質在遊戲內完全找不到可參考的原版檔案，因此無法修復，"
                 "已保持原樣。同一檔案中的其餘材質已正常修復。「強制修復」選項對此無效"
                 "（因為根本沒有可參考的對象）。",
        "zh_cn": "备注：{count} 个模组中，部分材质在游戏内完全找不到可参考的原版文件，因此无法修复，"
                 "已保持原样。同一文件中的其余材质已正常修复。「强制修复」选项对此无效"
                 "（因为根本没有可参考的对象）。",
        "ja": "注：{count}個のMODで、一部のマテリアルはゲーム内に比較対象となるバニラファイルが"
              "全く存在しなかったため修復できず、そのまま残されました。同じファイルの他のマテリアルは"
              "正常に修復されています。この場合「強制修復」オプションも効果がありません"
              "（比較対象自体が存在しないため）。",
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
        "zh_tw": "將模組原本套用的防具，移動到物理（碰撞/鏈條）結構相同的其他防具上。例如：與其他"
                 "模組的欄位衝突時，改套用不衝突的防具。\n選擇模組壓縮檔後，會自動偵測目前套用的"
                 "所有防具欄位 -- 若模組涵蓋多個欄位，可以逐一決定要移動或保持不變。",
        "zh_cn": "将模组原本套用的防具，移动到物理（碰撞/链条）结构相同的其他防具上。例如：与其他"
                 "模组的栏位冲突时，改套用不冲突的防具。\n选择模组压缩包后，会自动检测当前套用的"
                 "所有防具栏位 -- 若模组涵盖多个栏位，可以逐一决定要移动或保持不变。",
        "ja": "MODが現在対象としている防具を、物理（衝突/チェーン）構成が一致する別の防具に"
              "移動して適用できるようにします。例：他のMODとスロットが競合する場合に、"
              "競合しない防具へ移動。\nMODアーカイブを選択すると、現在対象としているすべての"
              "防具スロットを自動検出します -- MODが複数のスロットにまたがる場合は、"
              "それぞれ個別に移動するかそのままにするか決められます。",
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

    # ---- 적용 무기 변경 (weapon slot retargeting) -----------------------
    "btn_weapon_retarget": {
        "ko": "적용 무기 변경", "en": "Change Target Weapon",
        "zh_tw": "更換適用武器", "zh_cn": "更换适用武器", "ja": "適用武器の変更",
    },
    "tip_weapon_retarget": {
        "ko": "모드가 원래 목표로 하는 무기 모델을, 같은 무기 종류(대검/태도 등)의 다른 모델로 옮겨서 "
              "적용할 수 있게 해줍니다. 예: 다른 모드와 무기 슬롯이 겹칠 때 충돌 없는 모델로 옮기기.\n"
              "모드 압축파일을 선택하면 어떤 무기 모델을 목표로 하는지 자동으로 인식하고, "
              "같은 종류 안에서 옮길 수 있는 대상 목록을 보여줍니다.",
        "en": "Relocates a mod from the weapon model it currently targets onto a different model of "
              "the SAME weapon type (e.g. two Great Swords) -- e.g. to resolve a slot conflict with "
              "another mod. Pick a mod archive and this detects which weapon model it targets, then "
              "lists compatible targets within that same weapon type.",
        "zh_tw": "將模組原本套用的武器模型，移動到同一武器種類（如太刀對太刀）的其他模型上。例如："
                 "與其他模組的武器欄位衝突時，改套用不衝突的模型。\n選擇模組壓縮檔後，會自動偵測目前"
                 "套用的武器模型，並列出同種類中可移動的目標清單。",
        "zh_cn": "将模组原本套用的武器模型，移动到同一武器种类（如太刀对太刀）的其他模型上。例如："
                 "与其他模组的武器栏位冲突时，改套用不冲突的模型。\n选择模组压缩包后，会自动检测当前"
                 "套用的武器模型，并列出同种类中可移动的目标列表。",
        "ja": "MODが現在対象としている武器モデルを、同じ武器種（太刀と太刀など）の別のモデルに"
              "移動して適用できるようにします。例：他のMODと武器スロットが競合する場合に、"
              "競合しないモデルへ移動。\nMODアーカイブを選択すると、対象としている武器モデルを"
              "自動検出し、同じ武器種内で移動可能な対象の一覧を表示します。",
    },
    "dlg_weapon_retarget_title": {
        "ko": "적용 무기 변경", "en": "Change Target Weapon",
        "zh_tw": "更換適用武器", "zh_cn": "更换适用武器", "ja": "適用武器の変更",
    },
    "msg_weapon_retarget_no_file": {
        "ko": "이동할 모드 압축파일을 선택하세요.", "en": "Choose a mod archive to relocate.",
        "zh_tw": "請選擇要移動的模組壓縮檔。", "zh_cn": "请选择要移动的模组压缩包。",
        "ja": "移動するMODアーカイブを選択してください。",
    },
    "msg_weapon_retarget_no_weapon_found": {
        "ko": "이 모드에서 무기 모델을 정확히 하나만 찾지 못했습니다 (감지된 것: {found}).",
        "en": "Couldn't detect exactly one weapon model in this mod (found: {found}).",
        "zh_tw": "在此模組中未能偵測到唯一的武器模型（偵測到：{found}）。",
        "zh_cn": "在此模组中未能检测到唯一的武器模型（检测到：{found}）。",
        "ja": "このMODから武器モデルを1つだけ検出できませんでした（検出内容：{found}）。",
    },
    "msg_weapon_retarget_detected": {
        "ko": "감지된 무기 모델: {key} (mdf2:{mdf2} mesh:{mesh} pfb:{pfb}). "
              "아래 목록에서 옮길 대상을 선택하세요.",
        "en": "Detected weapon model: {key} (mdf2:{mdf2} mesh:{mesh} pfb:{pfb}). "
              "Select a target from the list below.",
        "zh_tw": "偵測到的武器模型：{key}（mdf2:{mdf2} mesh:{mesh} pfb:{pfb}）。"
                 "請在下方清單中選擇移動目標。",
        "zh_cn": "检测到的武器模型：{key}（mdf2:{mdf2} mesh:{mesh} pfb:{pfb}）。"
                 "请在下方列表中选择移动目标。",
        "ja": "検出された武器モデル：{key}（mdf2:{mdf2} mesh:{mesh} pfb:{pfb}）。"
              "下のリストから移動先を選択してください。",
    },
    "lbl_weapon_retarget_targets": {
        "ko": "변경 가능한 무기 모델 (같은 종류만)", "en": "Compatible target weapons (same type only)",
        "zh_tw": "可變更的武器模型（僅同種類）", "zh_cn": "可变更的武器模型（仅同种类）",
        "ja": "変更可能な武器モデル（同じ種類のみ）",
    },
    "col_weapon": {"ko": "무기 모델", "en": "Weapon model", "zh_tw": "武器模型", "zh_cn": "武器模型", "ja": "武器モデル"},
    "grade_weapon_exact": {
        "ko": "적용 가능", "en": "Compatible",
        "zh_tw": "可套用", "zh_cn": "可套用", "ja": "適用可能",
    },
    "grade_weapon_refused": {
        "ko": "적용 불가", "en": "Not safe to apply",
        "zh_tw": "不可套用", "zh_cn": "不可套用", "ja": "適用不可",
    },
    "grade_weapon_partial": {
        "ko": "물리 효과 소실 가능", "en": "Physics may be lost",
        "zh_tw": "物理效果可能消失", "zh_cn": "物理效果可能消失", "ja": "物理効果が消える可能性",
    },
    "note_weapon_missing_physics": {
        "ko": "모드가 자체 pfb를 포함하는데 대상에 없는 물리: {physics}",
        "en": "mod bundles its own pfb, but target lacks: {physics}",
        "zh_tw": "模組包含自己的 pfb，但目標缺少：{physics}",
        "zh_cn": "模组包含自己的 pfb，但目标缺少：{physics}",
        "ja": "MODが自前のpfbを含みますが、対象には次がありません：{physics}",
    },
    "note_weapon_partial_physics": {
        "ko": "모드에 포함된 물리(chain2 등) 파일이 대상에서 적용 안 될 수 있음 (대상에 없는 기본 물리: {physics})",
        "en": "the mod's bundled physics file (chain2 etc.) may not take effect on this target "
              "(baseline physics missing there: {physics})",
        "zh_tw": "模組附帶的物理檔案（chain2 等）在此目標上可能不會生效"
                 "（目標缺少的基礎物理：{physics}）",
        "zh_cn": "模组附带的物理文件（chain2 等）在此目标上可能不会生效"
                 "（目标缺少的基础物理：{physics}）",
        "ja": "MODに含まれる物理ファイル（chain2など）がこの対象では反映されない可能性があります"
              "（対象に不足している基本物理：{physics}）",
    },
    "msg_weapon_retarget_select_target": {
        "ko": "목록에서 옮길 대상 무기를 선택하세요.", "en": "Select a target weapon from the list.",
        "zh_tw": "請從清單中選擇要移動的目標武器。", "zh_cn": "请从列表中选择要移动的目标武器。",
        "ja": "リストから移動先の武器を選択してください。",
    },
    "msg_weapon_retarget_refused_blocked": {
        "ko": "이 대상은 모드가 포함한 pfb와 안전하게 호환되지 않아 적용할 수 없습니다 "
              "(CLAUDE.md #18 참고: ChainSetting 이식은 부팅 시 불안정함이 확인됨).",
        "en": "This target isn't safe to apply -- the mod's own bundled pfb wouldn't reconcile safely "
              "with it (see CLAUDE.md #18: ChainSetting transplant is confirmed unsafe at boot).",
        "zh_tw": "此目標無法安全套用 -- 模組自帶的 pfb 無法與其安全整合"
                 "（參見 CLAUDE.md #18：ChainSetting 移植已確認在開機時不穩定）。",
        "zh_cn": "此目标无法安全套用 -- 模组自带的 pfb 无法与其安全整合"
                 "（参见 CLAUDE.md #18：ChainSetting 移植已确认在开机时不稳定）。",
        "ja": "この対象は安全に適用できません -- MOD自体が含むpfbが安全に整合しません"
              "（CLAUDE.md #18参照：ChainSetting移植は起動時に不安定なことが確認済み）。",
    },
    "dlg_save_weapon_retarget": {
        "ko": "이동된 모드 파일 저장", "en": "Save relocated mod file",
        "zh_tw": "儲存移動後的模組檔案", "zh_cn": "保存移动后的模组文件", "ja": "移動後のMODファイルを保存",
    },
    "msg_weapon_retarget_done": {
        "ko": "저장했습니다:\n{path}", "en": "Saved:\n{path}",
        "zh_tw": "已儲存:\n{path}", "zh_cn": "已保存:\n{path}", "ja": "保存しました:\n{path}",
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
