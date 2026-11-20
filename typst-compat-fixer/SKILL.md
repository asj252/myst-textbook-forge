---
name: typst-compat-fixer
description: >
  修復 MyST Markdown / Jupyter Notebook(.md / .ipynb)在經由 MyST 編譯為
  Typst PDF 時的語法不相容問題。當使用者說「typst 編譯報錯」、「修 typst 相容性」、
  「the character '#' is not valid in code」、「\color 十六進制顏色報錯」、
  「xrightarrow 出錯」、「displaystyle 不支援」、「檢查 typst 相容」、
  「ref 順序 / label 未定義」、「mystmd 章節編號 / 交叉引用中文化」,
  或上傳教材章節並要求確保能用 Typst 匯出 PDF 時,
  必須觸發此 skill。也適用於在生成或編輯 MyST/ipynb 教材內容時,
  預防性地套用 Typst 相容寫法(命名顏色、Unicode 箭頭、:label: 選項、myst.yml 編號與交叉引用設定)。
---

# Typst 相容性修復(typst-compat-fixer)

Jupyter Book / MyST 將 `.md` 與 `.ipynb` 編譯為 Typst PDF 時,轉換器對部分
LaTeX 命令與 MyST 結構的支援有缺陷。本 skill 用「腳本 + 判斷」的混合流程修復:

- **腳本**(`scripts/fix_typst_compat.py`)完成所有確定性替換,並輸出報告。
- **執行者**根據報告處理需要上下文判斷的問題:引用順序、複雜 `\xrightarrow`、
  色差過大或色相偏移的顏色映射。

完整替換對照表與原理見 `references/substitutions.md`——處理任何
`needs_review` 項目之前先讀它。

## 工作流程

### 第 1 步：執行腳本

以下命令以 `/path/to/skill` 代指本檔所在的目錄。用執行腳本的 Python 3.10 以上環境安裝 `scripts/requirements.txt` 中的依賴，再執行修復。

```bash
python -m pip install -r "/path/to/skill/scripts/requirements.txt"
python "/path/to/skill/scripts/fix_typst_compat.py" ch01.ipynb -o fixed.ipynb --report report.json
python "/path/to/skill/scripts/fix_typst_compat.py" ch01.md ch02.ipynb --report batch.json
```

- 支援 `.md` 與 `.ipynb`。Notebook 只修 Markdown 格，保留 `source` 的字串或清單型別。程式碼格、原始格、輸出和中繼資料按 JSON 值保留。
- 預設另存為 `*.fixed.*`。單檔可用 `-o` 指定輸出。需要覆寫原檔時用 `--in-place`。`-o` 與多檔輸入或 `--in-place` 互斥。
- 腳本在寫入前檢查整批路徑及現存檔案別名，拒絕重複輸入或重合路徑。只有 `--in-place` 允許同一份文件的輸入和輸出重合。
- 文件和報告各自在目標目錄暫存，再以 `os.replace` 替換。失敗時以非零狀態退出，保留該目標先前的位元組並清理暫存。先前成功的文件會保留。報告等全部文件完成才寫。
- 單檔報告有 `color_replacements`、`command_replacements`、`needs_review` 三個頂層鍵。多檔時由 `files` 按輸入路徑收錄各檔報告。

腳本在行內和跨行的 `$…$`、`$$…$$`、`` {math}`…` `` 角色、冒號與反引號兩類 `{math}` directive 中修復命名色、箭頭和 LaTeX 命令。完整對照見 [替換表](references/substitutions.md)。腳本在 directive 的簡單單行選項把 `:name:` 改成 `:label:`，保留值、空白和 `%` 行尾註解。解析時保護 YAML、連結目標及標題、程式碼、HTML，以及 `code-cell`、`raw`、Mermaid 等程式碼或資料 directive。

### 第 2 步：核對報告和構建

逐項核對 `needs_review`。批次報告用 `files[檔案路徑].needs_review`。

- **`forward_reference`**。引用先於定義。可把引用移到定義之後，或改寫句子以維持原本的行文順序。調整內容順序前先向使用者說明。
- **`undefined_reference`**。用實際專案構建核對跨檔案目標，修正真斷鏈。腳本檢查 `ref`、`numref`、`eq`、`prf:ref`、`doc`，含 `文字 <target>`。定義取自獨立行錨點 `(label)=`、有效 directive 標籤、顯示公式尾標和顯示數學內的 `\label{…}`。
- **`ambiguous_source`**。核對 `context` 和 `reason`。來源邊界不明、選項續行或鍵有衝突、未知 directive 等片段原樣保留，其他可確認的片段繼續處理。
- **`math_backticks`**。美元公式整段保留。核對反引號的用途並人工改寫。
- **`complex_xrightarrow`**。按 [替換表](references/substitutions.md) 改寫該命令和參數。例如 `\xrightarrow[b]{a}` 可改為 `\underset{b}{\overset{a}{⟶}}`。
- **`color_distance_large`** / **`color_hue_mismatch`**。對照原色用途，確認最近命名色的區分度及冷暖色調。遇到 `unparseable_hex_color` 時，從原樣保留的色碼確認預期顏色。

`position` 是修復後的零起算字元位置。Notebook 按 Markdown 格順序累計，每個前面的 Markdown 格取修復後長度加 2，非 Markdown 格不計。到實際專案重跑目標構建，核對公式與引用。

### 第 3 步：匯報

用腳本摘要說明自動替換、人工處理、實際構建結果和待使用者定奪的項目。

## 預防模式

- 數學顏色使用命名色，例如 `blue`、`navy`、`teal`、`purple`、`orange`、`gray`。
- 箭頭及特殊符號可直接使用 Unicode（⟶、⟹、⟷、⟺、↑、↓、∉、ħ、■），遇到箭頭上方文字用 `\overset{…}{⟶}`。
- Directive 用 `:label:`，並先定義再引用。
- `myst.yml` 的章、節編號與中文引用見 [編號範本](references/substitutions.md#四mystmd-中文教材編號與交叉引用實測)。

## 常見錯誤訊息對照

| Typst 錯誤 | 根源 | 對應修復 |
|---|---|---|
| `the character '#' is not valid in code` | `\color{#hex}` | 顏色映射 |
| `unknown variable` / 命令未渲染 | LaTeX 命令相容性 | 命令替換表 |
| label / reference 相關錯誤 | 前向引用、斷鏈或 `:name:` | 第 2 步 |
| 章節編號錯亂 / `{.unnumbered}` 無效 / 引用顯示英文 | `myst.yml` 或頁面 frontmatter 編號設定 | 編號範本 |
