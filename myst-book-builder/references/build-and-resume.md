# 建構、真實執行與續跑

## 預檢與隔離

以下 `PYTHON`、`PDF_PYTHON`、`BROWSER`、`SKILL`、`INPUT`、`RUN` 都是本次選定路徑，先換成實際值。不要把範例變數當已存在的檔案。使用 Python 3.10 以上；公開腳本只需要標準庫、QA／列印階段的 websocket-client，合併階段的 pypdf。建書另需已安裝的 JB2、相容 theme、Node；計算庫與資料由書專案決定。

```bash
PYTHON SKILL/scripts/preflight.py --python PYTHON --browser BROWSER --out RUN/preflight.json
PYTHON -m jupyter_book --version
PYTHON -m jupyter_book build --help
```

`--python` 明確指定時，預檢在該解譯器內查版本；目前執行預檢的 Python 另列。PDF 處理可換既有 `PDF_PYTHON`，執行 `PDF_PYTHON -c "import pypdf; print(pypdf.__version__)"` 確認。缺少能力回報後停止對應階段，沒有自動安裝。conda 環境使用它的 Python，將其 prefix、Library/bin、Scripts 加到本次程序 PATH；不要只換 Python 而讓子程序使用另一個環境。Windows 設 `PYTHONUTF8=1`，為保留來源樹可同時設 `PYTHONDONTWRITEBYTECODE=1`。

在新的 `RUN/input` 放書稿、設定、引用與圖片的快照；資料可以複製或按專案約定唯讀引用。存相對路徑、bytes、SHA256；資料即使程式碼沒變也要取指紋。另存 Python／Node／JB／theme／kernel／重要計算庫版本、實際解譯器、環境選擇、命令與退出碼。快取也留在 run 內，來源書稿及舊快取保持原樣。

不擅自改動既有 Python／Node 的全域環境；已授權的建構可能在本次隔離 template 目錄執行工具內建的 web 依賴準備（例如 npm bootstrap），應記錄命令與實際位置，不概稱「沒有安裝任何東西」。

## fresh

先看實際版本 help，再選完整執行方式。JB2 的一個已驗證語法是：

```bash
PYTHON -m jupyter_book build --html --execute --execute-parallel 1
```

在 `RUN/input` 執行並把 stdout／stderr 存檔，退出碼原樣保留。不要把 `--site` 當已靜態匯出 HTML，也不要把 `--pdf` 當本 skill 的 Chromium 流程。使用者已有明確的執行器時沿用；例如先用 nbclient 執行隔離副本，再以 `build --html` 匯出，需記錄執行器和輸出 SHA，明說執行發生在匯出前。這不是通用內核排程器。

先核對一章 kernel 的 `sys.executable` 和輸出，再跑全書；只觀察本次建立的服務／kernel。全部執行結束後，從該版本實際產生的執行結果逐格核對：預期格數、執行計數或等效逐格證據、無 error、數值／圖像輸出及結果 SHA。不要只看進度字樣或無 error 格；無輸出的靜默格還需要執行溯源。Notebook cache 格式隨 JB 版本變動，先檢查實際 schema，不能照搬別版的程式碼鍵。

## resume

續跑只接受同一隔離 run、完整且可歸屬的成功結果。記錄前次的執行命令、真實退出或停止原因、輸入／資料／依賴指紋、每本 Notebook 程式碼與結果 SHA、已執行格數和錯誤數。先比對這些，再核對原生快取鍵；原生鍵通常不能證明外部資料或庫版本沒變。

改動資料、kernel、重要依賴或輸入後，舊來源記錄不能直接當有效 resume：建立新 run，或將受影響格重新真實執行並記錄依賴判斷。不得將 resume 稱為 fresh。卡住後中止僅代表保存進度；最終仍要全部執行證據、完整 HTML 匯出退出 0 和後續 QA。清快取僅限新 run 或明確屬於本次的快取；先留失敗紀錄，不刪原專案資料。

網站生成後檢查 `config.json`、toc 和每頁 JSON 的 `location`；`qa_site.py` 使用這套映射，不以遞迴搜尋所有 md／ipynb 代替 toc。靜態站只含一個 project 是目前腳本的邊界；多 project 分別處理。
