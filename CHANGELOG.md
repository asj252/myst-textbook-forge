# 變更記錄

## 0.2.0（2026-10-19）

### 倉庫

- README 開頭加頭圖 `assets/readme/hero.svg`：倉庫的標誌（幾何鐵砧）、一句話說明與三個 skill 的標籤。

### python-textbook-code-optimizer

- 規則 3 寫明 `compare_print` 的 `expected_desc` 可傳教材公式算出的數值、NumPy 陣列或說明文字，並補公式兩邊對比的例子。
- 規則 5 寫明無繪圖與含繪圖時完整的初始化順序（`import` → 配色常數 → printoptions／rcParams → 輔助函數 → 樣板）。
- 「畫布背景」`C_BG` 在 matplotlib 下只設座標軸繪圖區（`ax.set_facecolor`），Figure 外圍保持預設。
- 新增「執行驗證（Jupyter Book 緩存清理）」一節：在教材專案裡真實執行範例前，先清理執行緩存。

### textbook-visual-style

- 寫明等比例、正方形預設外框與固定範圍的約束：未固定的範圍可向外擴展，固定的範圍保留，三者不相容時先問使用者。
- 「畫布背景」的範圍與 python-textbook-code-optimizer 一致：matplotlib 只設繪圖區，plotly 的繪圖區與紙面都設 `C_BG`。
- 主題初始化用於所有 Mermaid 圖型；classDef 只用於 flowchart／graph，sequenceDiagram 等用各自的語法。
- 結構層（spines、刻度、標題、軸線、原點文字）補程式碼，一律用 `C_AXIS`。
- 變換前後完全重合的向量畫一支共用箭頭，文字分別標前後狀態並說明 Av = v。
- 無頭 Chrome 印 PDF：在頁面腳本執行前設淺色主題，逐圖等渲染完成後列印，並在 PDF 裡逐圖核對完整標籤。

### textbook-chapter-editor

- label 索引改用共用的 markdown-it-py／mdit-py-plugins 解析層；加入粗體閉合候選掃描與靜態網頁互動輸出的處理規則。

## 0.1.0（2026-10-15）

首次發布，三個 skill：

- `textbook-visual-style`：教科書的統一視覺規範。公開時把作者的品牌配色換成一套示例配色（保留每個顏色的語義角色），刪去對書稿設計系統的引用，Mermaid 套樣式改為不用 `:::` 行內寫法。
- `python-textbook-code-optimizer`：Python 範例代碼的教科書排版。公開時寫明完整代碼的順序（函數定義在例題樣板之前），避免照字面放在檔案開頭而出錯。
- `textbook-chapter-editor`：繁體中文大學線性代數教材的章節編輯。公開時去掉書稿專用的路徑與命名，把行／列等術語慣例收成隨 skill 附帶的參考檔；重寫全書 label 索引腳本：程式碼示例不收集、directive 內文照 MyST 的方式切分、標題前的錨點歸到該標題、讀檔失敗或 notebook 不合法時停下而不寫報告、不同目錄的同名檔案分開；切分可能與 MyST 不同的幾類寫法列在報告末尾「需要人工確認的位置」。
