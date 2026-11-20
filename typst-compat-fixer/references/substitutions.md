# LaTeX / MyST → Typst 替換對照表

本表是 `scripts/fix_typst_compat.py` 中替換規則的完整說明與擴充指引。
遇到腳本未覆蓋的新問題時,先在此確認是否已有慣例,再決定修法;
確立新規則後,同步加入腳本的 `COMMAND_SUBS` 或 `EXPLICIT_COLOR_MAP`。

## 一、數學環境中的顏色

**問題根源**:`#` 是 Typst 的代碼模式控制符。MyST→Typst 轉換器遇到
`\color{#1F4E9C}{1}` 時會把顏色截斷,生成 `#text(fill: #)[...]`,
Typst 報錯 `the character '#' is not valid in code`。

**修法**:一律改用命名顏色。候選集取 Typst 內建色與 KaTeX/CSS 的交集:
`black, gray, silver, white, navy, blue, aqua, teal, purple, fuchsia,
maroon, red, orange, yellow, olive, green, lime`

**教材預設調色盤顯式映射**(腳本 `EXPLICIT_COLOR_MAP`,與 `textbook-visual-style` 6 色對齊):

| 十六進制 | 語義角色 | 命名顏色 |
|---|---|---|
| `#1F4E9C` | 主藍(primary) | `blue` |
| `#2F3E5C` | 深藍(slate / secondary) | `navy` |
| `#1A9E8F` | 青綠(teal) | `teal` |
| `#6A4C93` | 紫(purple) | `purple` |
| `#D9480F` | 強調橙(accent / orange) | `orange` |
| `#8FA3BF` | 中性灰(muted / gray) | `gray` |

未列出的十六進制色按 RGB 歐氏距離取最近命名色。支援 `#RGB`、`#RRGGBB`、`#RRGGBBAA` 與六位 `[HTML]`。RGB 計算略過 alpha，顯式映射用完整色碼查表。`#1F4E9C` 映射為 `blue`，`#1F4E9C80` 映射為 `teal` 並告警。舊格式中無法解析的色碼原樣保留，列入 `unparseable_hex_color`。

- RGB 距離大於 120.0 時報 `color_distance_large`。
- RGB 距離未超過門檻時，若兩色的 HSV 飽和度都至少為 0.25，圓周色相差取到小數一位。結果大於 30.0° 時報 `color_hue_mismatch`。
- `#006385` 映射為 `teal` 且無告警。`#8B4513` 映射為 `olive`，RGB 距離為 63.0，HSV 色相差為 35.0°。

注意:此規則只針對**數學環境內**(`$...$`、`$$...$$`、`` {math}`...` ``、```` ```{math} ````、`:::{math}`)的 `\color` / `\textcolor`,且支援 `{ \color{#XXXXXX} x }` 無第 2 組大括號的寫法與跨行公式。
普通段落、YAML frontmatter、程式碼區塊(含引用區塊內的縮排程式碼)、行內反引號、HTML 註解(含同行連續多段)與 matplotlib 等 Python 代碼中的十六進制色完全不受影響,不要動它們。

## 二、LaTeX 命令替換

| 原命令 | 替換為 | 說明 |
|---|---|---|
| `\Uparrow` | `↑` | 直接用 Unicode |
| `\Downarrow` | `↓` | |
| `\hbar` | `ħ` | |
| `\blacksquare` | `■` | 亦可用 `\square`,擇一保持全書一致 |
| `\iff` | `⟺` | |
| `\Longleftrightarrow` | `⟺` | |
| `\longleftrightarrow` | `⟷` | |
| `\longrightarrow` | `⟶` | |
| `\Longrightarrow` | `⟹` | |
| `\bmod` | `\operatorname{mod}` | |
| `\notin` | `∉` | |
| `{\sf T}` / `\sf T` | `\top` | 轉置符號 |
| `\displaystyle` | (刪除) | Typst 不支援 |
| `\scriptstyle` | (刪除) | Typst 不支援 |
| `\xrightarrow{x}` | `\overset{x}{⟶}` | 轉換器對 `\xrightarrow` 有 bug |

以上命令替換與 `\displaystyle` / `\scriptstyle` 刪除僅在**數學環境內**執行,且命令名結尾皆帶 `(?![a-zA-Z])` 邊界檢查(避免誤傷同前綴的長命令)。

`\xrightarrow` 的複雜形式(含 `[下方文字]` 或嵌套大括號,如 `\xrightarrow{\text{def}}`)腳本不自動處理,
會進入 `needs_review`(`complex_xrightarrow`)。執行者手動改寫時的一般策略:
- `\xrightarrow[below]{above}` → `\underset{below}{\overset{above}{⟶}}`
- 嵌套大括號:人工確認括號配對後套用 `\overset{...}{⟶}`(例如 `\xrightarrow{\text{def}}` → `\overset{\text{def}}{⟶}`)

已知限制(逐項人工確認):
- 美元界定的數學公式內含反引號文字(如 `$\displaystyle \text{`x`}$`):腳本保留整個公式,以 `math_backticks` 回報 `position`(修復後文字的零起算字元位置;notebook 按 markdown cell 順序累計)與 `context`,請人工改寫並確認。
- 複雜 `\xrightarrow`(可選參數或嵌套大括號):維持上述 `complex_xrightarrow` 報告與人工處理方式。

## 三、MyST 結構規則

1. **引用順序**。腳本檢查 `ref`、`numref`、`eq`、`prf:ref`、`doc`，含 `文字 <target>` 寫法。定義來自獨立行錨點 `(label)=`、有效的 directive 標籤、顯示公式尾標 `$$ (label)` 及顯示數學中的 `\label{…}`。按原文順序辨別 `forward_reference` 和 `undefined_reference`。跨檔案目標須以實際建書驗證。
2. **Directive 選項**。簡單單行 `:name:` 改為 `:label:`，保留值、空白和 `%` 行尾註解。合法 YAML 選項中明確的單一 `label` 可作定義，整段 YAML 保持原樣。遇到選項續行或重複鍵，保留該段並回報 `ambiguous_source`。簡單的 `:label:` 和 `:name:` 並存時，沿用原 `:label:` 並回報衝突。程式碼／資料 directive 的選項和正文整段保護。

## 四、`mystmd` 中文教材編號與交叉引用實測

以下書稿結果來自 Jupyter Book 2.1.5 與既有 `book-theme`。章、節用 `build --html` 核對，標題深度及反例用 `build --site` 核對，兩次均未執行 notebook。配置格式見 [MyST 官方編號指南](https://mystmd.org/guide/cross-references#numbering)。

### 1. 章、節編號和引用文字

```yaml
project:
  numbering:
    title: {enabled: true, offset: 0}
    headings: true
    heading_3: {enabled: false}
    equation: {template: "式 (%s)"}
    exercise: {template: "習題 %s"}
    proof:theorem: {template: "定理 %s"}
    proof:definition: {template: "定義 %s"}
    proof:example: {template: "例 %s"}
    proof:property: {template: "性質 %s"}
```

1. **章、節**。T126（`727d883`）用 `title` 與 `headings` 配合，原書章號為 1–26，節號為 N.1 等。
2. **不編號頁**。T126 在導讀、符號表各自的頁面 frontmatter 加上 `numbering: {title: false, headings: false}`。這些頁的標題和節均不占編號。
3. **標題深度**。T127（`a54cfcf`）用 `heading_3: {enabled: false}` 關閉三級標題編號，二級標題仍編號。
4. **中文引用**。在 `project.numbering` 下並列 `equation`、`exercise`、`proof:theorem`。原書有定理及習題中文引用，三頁預檢另核對了「式 (1)」「定理 1」「習題 1」。定義、例和性質可用範本中的對應鍵。
5. **頁面設定的兩個反例**。T127 的 `### 標題 {.unnumbered}` 未關閉編號。頁級 `numbering.enumerator` 會影響章、節，試建把第 3 章改成 3.3。
6. **生成框標題**。T127 的網站定理、習題框仍為英文，原書安排在印刷時替換框標題。上述範本控制引用文字。其他網站主題及 Typst 模板須各自構建驗證。

## 五、擴充新規則

新的不相容命令 → 加入 `COMMAND_SUBS`(注意把長命令放在短命令前面,
避免部分匹配);新的調色盤顯式色 → 加入 `EXPLICIT_COLOR_MAP`。
每次擴充後在一個最小 `.md` 樣例上跑一遍腳本驗證。
