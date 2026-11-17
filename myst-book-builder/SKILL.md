---
name: myst-book-builder
description: 使用既有 Python／Jupyter Book 2 環境建 MyST 網站、執行全書 Notebook、檢查 hydrated HTML，再以 Chromium 逐章列印及合併有導航的 PDF。當使用者要求建站、全書執行、網站 QA、逐章或全書 PDF 時使用；本版不處理 Jupyter Book 1、LaTeX 或 Typst。
---

# MyST 建書與印刷

把來源、執行結果、網站和 PDF 接成可追溯的一次 run。優先使用使用者指定的既有環境；缺依賴先報告，不自動安裝、升級或改全域設定。

## 建構與執行

先讀 [建構與續跑](references/build-and-resume.md)。用 `scripts/preflight.py` 確認所選 Python、Jupyter Book、Node 與 Chromium 路徑。QA／列印與 PDF 合併可以使用不同的既有 Python。

在新的隔離目錄複製書稿、設定和所需資料，先存完整輸入與依賴指紋。清楚選擇 fresh 真實執行或已有證據的 resume；不要把未執行的來源 Notebook、原生快取命中或受控停止寫成全書執行成功。核對全部預期程式格、錯誤和代表輸出；靜默格可以沒有輸出。需要修補時只改本次副本，保留逐項差異與原因。

## 網站與 PDF

讀 [印刷與 QA](references/printing-and-qa.md)，依序執行：

1. `qa_site.py HTML_DIR QA_DIR --browser BROWSER --source-dir INPUT_DIR`：按實際 toc 查全部頁、公式、Mermaid、圖片、解答、標題與書內連結。外鏈另列為未驗證。阻斷回傳非零；寬度風險交列印幾何處理。
2. `print_pages.py HTML_DIR PARTS_DIR --browser BROWSER --expect QA_DIR/qa_report.json --evidence EVIDENCE_DIR`：所有語言模式共用就緒硬門，預設 `--lang preserve`；可選 `zh-Hans`／`zh-Hant`，僅替換生成框標題與對應引用。QA 與 config、toc、逐頁 HTML／JSON／來源指紋不符就停止。
3. 從新產生的 `print_manifest.json` 讀取 `print_origin`，原樣傳給 `merge_pdf.py --manifest MANIFEST --out BOOK.pdf --report REPORT.json --print-origin ORIGIN`。不要猜 port，也不要從 PDF 的 localhost 連結反推。`--pages` 是不完整調試輸出，合併會拒絕。
4. 將 PDF 轉 PNG，實際打開圖頁與其前後頁、長行內代碼頁、第一末頁。每幅 Mermaid 在圖內逐一核對完整標籤和箭頭、標題是否與圖同頁、文字是否可讀。機器幾何、字串命中與截圖存在都不能代替這一步；記下實際看過的頁碼與觀察，未完成就保留待驗證狀態。

交付來源→slug→分件→合併頁碼→SHA 的映射、真實命令／退出碼、環境、執行溯源、QA、列印及導航報告、視覺紀錄和未驗證項。書專案直接呼叫本 skill 的入口，記錄版本／可得的來源 commit 與腳本 SHA；需要 vendor 時先比較來源和 SHA，再依專案授權更新，沒有自動覆蓋同步器。

遇到條件性故障才讀 [診斷](references/troubleshooting.md)，先保留失敗現場，再對本次 run 做最小修正。
