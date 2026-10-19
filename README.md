<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="myst-textbook-forge：用 MyST／Jupyter 寫數學教科書時用的 agent skill——圖表視覺風格、Python 代碼排版、章節編輯與 label 索引">
</p>

# myst-textbook-forge

用 MyST Markdown／Jupyter Notebook 寫數學教科書時用的 agent skill：統一圖表的視覺風格、把 Python 範例代碼整理成教科書排版、編輯章節（小結、練習、全書 label 索引）。每個 skill 是一個目錄，核心是一份 `SKILL.md`，放進能讀取 skill 目錄的 agent 宿主即可使用。

> **English.** myst-textbook-forge is a small set of agent skills for writing math textbooks in MyST Markdown and Jupyter Notebooks: a consistent visual style for plots and Mermaid diagrams, textbook-style formatting for Python example code, and chapter editing (section summaries, exercises, and a book-wide label index with duplicate and broken-reference checks). The skills are written in Traditional Chinese for now; an English version is planned. Each skill is a folder with a `SKILL.md`; copy it into the skills directory your agent host reads.

> 狀態：試用版（0.2.0）。每個 skill 都由一個只讀公開稿的執行者在陌生樣例上跑通過一次，並經獨立審查；0.2.0 發布前，兩個繪圖相關 skill（`python-textbook-code-optimizer`、`textbook-visual-style`）又各在另一個 agent 宿主上照公開稿跑過一次樣例（Plotly 寫法與 Jupyter Book 執行緩存的清理未實際驗證）。樣例都很小。目前以繁體中文發布，之後會整體改寫成英文版。

## 相關倉庫

同一作者的其他 skill 倉庫：

- [persona-masks-cn](https://github.com/asj252/persona-masks-cn)：讓 AI 助手把「想、做、查」分開的一套輕量角色約定，做成檔案型 skill。
- [chinese-math-forge](https://github.com/asj252/chinese-math-forge)：中文數學教材的寫作與審查工具：數學嚴謹性審查、繁英翻譯與習題流水線。
- [writing-forge](https://github.com/asj252/writing-forge)：寫作用的 skill：講解文章的認知審查、忠於原文的簡報、README 頭圖設計。


## 包含的 skill

| skill | 做什麼 |
|---|---|
| [`textbook-visual-style`](textbook-visual-style/SKILL.md) | 教科書的統一視覺規範：matplotlib／plotly 的色彩常數與圖層用色、中文字型、背景與格線、向量一律用 `quiver`，以及 Mermaid 的主題與語義樣式。色碼是一套示例，按角色換成自己的配色 |
| [`python-textbook-code-optimizer`](python-textbook-code-optimizer/SKILL.md) | 把 Python 範例代碼整理成教科書排版：全域輸出格式、步驟標題、「代碼計算值」與「公式預期值」對照、例題樣板；有繪圖時同時套用 `textbook-visual-style` |
| [`textbook-chapter-editor`](textbook-chapter-editor/SKILL.md) | 編輯繁體中文的大學線性代數教材章節：章節掃描、各節小結、全章總結與知識結構圖、學習目標、練習模塊，以及全書 label 索引、重複與斷鏈檢查（附腳本） |

## 安裝

把需要的 skill 目錄整個複製到宿主讀取 skill 的位置（各宿主一般有使用者層級與專案層級兩種 skills 目錄，見宿主自己的文件），目錄名保持與 `SKILL.md` 裡的 `name` 一致：

```bash
git clone https://github.com/asj252/myst-textbook-forge.git
SKILLS_DIR="$HOME/path/to/skills"   # 先換成宿主實際讀取的 skills 目錄
mkdir -p "$SKILLS_DIR"
cp -r myst-textbook-forge/textbook-visual-style "$SKILLS_DIR/"
```

`python-textbook-code-optimizer` 引用 `textbook-visual-style`，兩個一起裝。執行時用到的是宿主本身的能力：讀寫檔案；`textbook-chapter-editor` 的 label 索引腳本要宿主能執行 Python 3 腳本（Python 3.10 以上；解析依賴見該 skill 的 `scripts/requirements.txt`）。skill 產出的範例代碼要在你自己的環境執行時，按所用的庫準備（NumPy、matplotlib 或 plotly）；這些不是安裝 skill 的前提。

## 已知限制

- `textbook-chapter-editor` 的範圍是繁體中文的大學線性代數教材（練習要求具體的矩陣或向量）。label 與粗體檢查改用 markdown-it-py 與 mdit-py-plugins；塊級只取行號，行內按段落差分，不一致或定界未配對的整段保留並逐行列入人工確認，其餘段落繼續；專案自訂 directive 的特殊語義需人工核對，實際支援的擴充見 SKILL。
- `textbook-visual-style` 還沒寫清楚的兩處：未指定範圍、向外擴展較短方向時，自動邊距與中心怎麼定；flowchart 的「重要分類」與「結構性概念」兩類怎麼區分。下一版補。
- 兩個繪圖相關 skill 的樣例各在一個 matplotlib 3.10 的環境實際執行過一次（數值與出圖正確）；plotly 的部分與其他版本沒有驗證。

## 許可

本倉庫以 [Apache-2.0](LICENSE) 發布。三個 skill 都是作者自己的書稿工具，公開時去掉了書稿專用的路徑、命名與品牌配色。

變更記錄見 [CHANGELOG.md](CHANGELOG.md)。
