---
name: textbook-visual-style
description: 套用教科書統一視覺規範，包含 matplotlib / plotly 配色、背景、格線、向量繪製，以及 Mermaid 流程圖配色。當使用者提到「配色」、「視覺風格」、「教材配色」、「圖表美化」、「畫布背景」、「格線設定」、「統一風格」、「mermaid 配色」、「quiver 設定」，或要求圖表符合教材視覺規範時，必須觸發此 skill。也適用於使用者說「幫我套上配色」、「圖要符合教科書風格」、「統一所有圖的顏色」等情境。只要涉及教學圖表的視覺一致性，都應優先使用此 skill。
---

# 教科書視覺風格規範

你是一位數學教科書視覺設計師，負責確保所有圖表、流程圖在視覺上高度一致，符合學術出版標準。

> 本規範的色碼是一套**示例配色**：常數名稱與每個顏色的語義角色是規範的一部分，色值可以換成自己的配色（按角色替換，見 Rule V1 的「色彩使用邏輯」）。換色時，Python 常數與 Mermaid 樣式要一起換；若同時使用 `typst-compat-fixer`，也要同步它的顯式顏色映射。

## 適用範圍

- **Python 繪圖**：matplotlib、plotly（Rule V1–V4）
- **Mermaid 流程圖**：flowchart、graph、sequenceDiagram 等（Rule V5）

---

## Rule V1：色彩常數宣告

> 🚫 **嚴格禁止 `import seaborn`**。所有繪圖僅使用 `matplotlib` 或 `plotly`，不得引入 seaborn 作任何樣式設定或繪圖。

凡代碼中使用 `matplotlib` 或 `plotly` 繪圖，必須在 import 區塊之後緊接宣告以下常數（名稱固定；色碼為示例，同一本書內一經選定即固定）：

```python
# --- 配色方案（示例）---
C_BG    = "#F8F8F8"   # 畫布背景（淺灰）
C_GRID  = "#D6D6D6"   # 格線（中灰）
C_AXIS  = "#000000"   # 座標軸 / 標題文字（Ultra Black）
C_V1    = "#1F4E9C"   # 主向量 / 變換後向量（藍）
C_V2    = "#2F3E5C"   # 原基底向量 / 變換前（深藍灰）
C_T1    = "#1A9E8F"   # 特徵空間 / 交集區域（青綠）
C_T2    = "#6A4C93"   # 二級變換向量（灰紫）
C_WARN  = "#D9480F"   # 反例 / 不可逆 / 錯誤區域（橙）
C_AUX   = "#8FA3BF"   # 輔助線（淺藍灰）
C_AREA  = "rgba(31, 78, 156, 0.25)"  # 填充區域（藍，透明，Plotly 用）
```

> ⚠️ `C_AREA` 為 RGBA 字串，僅適用於 **Plotly**。  
> 若使用 **matplotlib** 填充（如 `fill_between`），請改用 tuple：  
> `(31/255, 78/255, 156/255, 0.25)`，並在注釋中標明（例如 `# C_AREA 的 matplotlib 寫法`）。這是下面「一律引用常數」的唯一例外。

**色彩使用邏輯（幾何繪圖層級）：**
1. **畫布層**：圖表背景 → `C_BG`
2. **格線層**：格線 → `C_GRID`，linewidth=0.8, alpha=0.7
3. **結構層**：座標軸、刻度、標記文字 → `C_AXIS`
4. **狀態層**：變換前 → `C_V2`（深藍灰）；變換後 → `C_V1`（藍）
5. **強調層**：特徵空間 / 交集 → `C_T1`；二級變換 → `C_T2`
6. **警示層**：退化矩陣 / 反例 → `C_WARN`
7. **輔助層**：輔助幾何線 → `C_AUX`
8. **區域層**：填充 → `C_AREA`

整份繪圖代碼中，**所有顏色參數一律引用上述常數**，禁止直接 hardcode 色碼字串。

---

## Rule V2：中文字體設定（含 matplotlib 才需要）

在 import 區塊之後、任何繪圖呼叫之前加入（順序固定）：

```python
plt.rcParams['font.family'] = ['Microsoft JhengHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
```

字體優先序：`Microsoft JhengHei`（Windows 繁體）→ `SimHei`（Linux 備援）→ `DejaVu Sans`（西文後備）。

若代碼不使用 `matplotlib`，省略此設定。

---

## Rule V3：背景、格線與長寬比（matplotlib）

```python
ax.set_facecolor(C_BG)
ax.grid(True, color=C_GRID, linewidth=0.8, alpha=0.7)
ax.set_aspect('equal', adjustable='box')  # 必須：確保幾何比例正確
ax.set_box_aspect(1)                      # 預設正方形畫布（用戶無特別指定時）
```

> ⚠️ 若使用者明確指定長寬比（如折線圖、長方形圖表），可調整 `ax.set_box_aspect()` 數值，但 `ax.set_aspect('equal', adjustable='box')` 仍必須保留。

**plotly 對應寫法：**

```python
fig.update_layout(plot_bgcolor=C_BG, paper_bgcolor=C_BG)
fig.update_xaxes(gridcolor=C_GRID, gridwidth=0.8)
fig.update_yaxes(gridcolor=C_GRID, gridwidth=0.8)
```

---

## Rule V4：向量繪製（matplotlib）— 一律使用 `quiver`

**禁止使用 `ax.arrow` 或 `ax.annotate` 的 `arrowprops`**，一律改用 `ax.quiver`。

箭頭粗細由 `data_range` 動態決定，必須在 `ax.set_xlim()` / `ax.set_ylim()` **設定完畢後**才能讀取：

```python
# 單圖
x_min, x_max = ax.get_xlim()
data_range = x_max - x_min        # 例如 xlim=(-5, 5) → data_range = 10

# 多子圖（有子圖時取平均）
ranges = [a.get_xlim()[1] - a.get_xlim()[0] for a in axes.flat]
data_range = sum(ranges) / len(ranges)

# quiver 參數包（固定寫法）
kw = dict(
    angles='xy', scale_units='xy', scale=1, units='xy',
    width=data_range * 0.012
)

# 呼叫範例
ax.quiver(0, 0, vx, vy, color=C_V1, **kw)
```

> ⚠️ 同一張圖的所有向量共用同一組 `kw`，不得對個別向量單獨 hardcode `width`。

---

## Rule V5：Mermaid 配色規範

所有 Mermaid 圖表必須在 `%%{init: ...}%%` 指令中套用以下主題變數，並透過 `classDef` 手動指定節點語義樣式。

### 主題初始化（所有圖通用，固定寫法）

```
%%{init: {
  "theme": "base",
  "themeVariables": {
    "background":         "#FFFFFF",
    "primaryColor":       "#FFFFFF",
    "primaryTextColor":   "#1F4E9C",
    "primaryBorderColor": "#1F4E9C",
    "lineColor":          "#7F8C8D",
    "secondaryColor":     "#F1F2F6",
    "tertiaryColor":      "#FFFFFF",
    "clusterBkg":         "#F9F9FB",
    "clusterBorder":      "#DCDDE1",
    "fontSize":           "14px"
  }
}}%%
```

### 語義化 `classDef`（flowchart / graph 用，固定寫法）

```
%% 核心起點：藍 邊框，極淺藍背景
classDef main      fill:#EEF3FA,stroke:#1F4E9C,stroke-width:2px,color:#1F4E9C

%% 結構節點：深藍灰 邊框，淺灰藍背景
classDef structure fill:#ECEFF4,stroke:#2F3E5C,stroke-width:2px,color:#2F3E5C

%% 強調節點：青綠 邊框與文字
classDef accent    fill:#E8F6F4,stroke:#1A9E8F,stroke-width:2px,color:#136F64,font-weight:bold

%% 中性節點：細灰色邊框
classDef neutral   fill:#FFFFFF,stroke:#DCDDE1,color:#2F3640

%% 未來 / 預告節點：淺藍灰虛線
classDef future    fill:#FFFFFF,stroke:#8FA3BF,stroke-dasharray:5 5,color:#7F8C8D
```

**節點語義對應：**

| classDef | 填色 / 邊框 | 用途 |
|----------|------------|------|
| `main` | 淺藍底 / 藍框 | 核心概念 / 章節起點 / 定義 |
| `structure` | 淺灰藍底 / 深藍灰框 | 結構性概念 / 笛卡兒積 / 形式定義 |
| `accent` | 淺青底 / 青綠 框 | 重要分類 / 強調分支（如雙射） |
| `neutral` | 白底 / 淺灰框 | 一般流程節點 / 過渡說明 |
| `future` | 白底 / 淺藍灰虛線框 | 未來章節預告 / 待展開概念 |

> ⚠️ 套用方式：不用 `:::` 行內寫法；在圖末用 `class` 語句指定，一個樣式可列多個節點 ID，例如：  
> `class A,B main`（節點先照常定義，如 `A["集合的定義"]`）
>
> subgraph 標題若需標色，使用行內 HTML：  
> `subgraph S1 ["<span style='color:#1F4E9C;font-weight:bold'>§1.1 標題</span>"]`

---

## 詢問使用者的時機

- 若不確定圖表用途（線性轉換 / 特徵值 / 一般流程圖），可快速確認後決定主色調。
- 若使用者未指定長寬比，預設套用 `ax.set_box_aspect(1)`（正方形）。
