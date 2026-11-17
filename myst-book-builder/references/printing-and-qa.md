# HTML QA、列印與導航

先完成建構與執行溯源，再以新目錄保存每次 QA／列印。命令中的大寫路徑需換成實際值：

```bash
PYTHON SKILL/scripts/qa_site.py HTML_DIR QA_DIR --browser BROWSER --source-dir INPUT_DIR
PYTHON SKILL/scripts/print_pages.py HTML_DIR PARTS_DIR --browser BROWSER --expect QA_DIR/qa_report.json --evidence EVIDENCE_DIR --lang preserve
PDF_PYTHON SKILL/scripts/merge_pdf.py --manifest PARTS_DIR/print_manifest.json --out RUN/book.pdf --report RUN/navigation.json --print-origin ACTUAL_ORIGIN
```

`ACTUAL_ORIGIN` 從這次 `print_manifest.json` 的 `print_origin` 讀取。HTTP 與 CDP 都使用動態 port，獨立臨時 browser profile，在 finally 只關閉本次服務／瀏覽器。腳本不讀使用者 profile，不全機 kill。HTML 必須是 JB2／MyST 的靜態輸出，有 `config.json`、`index.json` 及逐頁 JSON；找不到會非零，不會退回猜章節。

## 報告與硬門

`qa_report.json` 保存完整 toc、有序來源頁面、config／toc／HTML／JSON／可選來源 SHA、腳本 SHA、hydrated DOM 計數及內部 href。外鏈列 `checked:false`，不聲稱 HTTP 可達。缺頁、錯頁、未 hydration、公式錯誤、缺圖／空白 Mermaid、缺解答、書內斷鏈或標題層級跳號是阻斷。過寬物件先列 width risks；列印時重新檢查幾何。

列印前所有語言模式都核對 QA 與目前完整輸入相同，並重新等唯一文件請求 HTTP 200、正確 URL、React hydration、字型、公式／圖／圖片數量和解答。提前初始化淺色，展開 details，圖片改 eager。只有全部硬門與幾何通過才呼叫 Chromium 列印。

預設 A4、上下面距 15mm、左右 14mm；可用寬高與縮圖計算使用同一設定。代碼保留字面空白並以 `break-spaces`／`overflow-wrap:anywhere` 換行；不用裁切遮住溢出。圖、公式、圖片按可用尺寸等比適配；高 Mermaid 連緊鄰小標題計算高度。低於 60% 的縮放列入 `small_objects`，必須檢查可讀性；仍超頁或橫溢就阻斷。若版面特殊，先在隔離輸出副本做局部調整、留前後 SHA，再重跑 QA 和列印。

`--lang preserve` 保留原生成詞。`zh-Hans`／`zh-Hant` 只處理已登記生成框標題與對應引用的英文類型詞；不改源稿、編號、href、DOM 結構和非目標文字，前後核對及 SHA256 寫入逐頁證據。引用須同時符合 AST 生成語義、目標頁面與完整生成標籤；作者普通連結若與生成引用無法唯一對應，保留文字並阻斷換字，可改用 preserve 保留原文。遇到 theme 的未支援標題形式，先檢查 DOM 並報未轉換處，不能用全頁替換。換字後仍須視覺查看解答標題語序。

## 交接與合併

列印自動產生 `print_manifest.json`。`schema`、`success`、`complete`、`print_origin`、`inputs`、`qa_sha256`、`pages`、`evidence_index` 及其 SHA 構成交接；每頁含 slug、source、title、HTML／JSON／來源指紋、part 路徑／SHA、逐頁證據路徑／SHA。index 同時保存實際 origin、逐頁成功與 part SHA。`--pages index slug ...` 可除錯，但 `complete:false`；不能合併成全書。

合併先核對 origin、完整狀態、有序頁面映射、index、part 和逐頁證據 SHA。各原 PDF 的重名目的地先在原分件內解成頁碼與座標，才合併，避免全域 named destinations 重名錯跳。只有精確 print-origin 的已知 slug 連結離線化；其他 HTTPS 或另一 localhost origin 原樣保留並分類。精確 origin 的未知頁或 fragment 阻斷。重開輸出驗頁數、書籤順序、全部轉換目標與座標、保留外鏈和原內容流；不完整結果不寫成成功 PDF。這些核對防誤接，不能防人為同時偽造全部證據。

`navigation.json` 的 `parts` 給來源→slug→part→合併起頁／頁數→SHA。合併機器通過仍不代表分頁或圖像通過。

## PDF 必須實際看圖

以可用 PDF renderer 將完整頁轉成 PNG，例如：

```bash
pdftoppm -png -r 120 RUN/book.pdf RUN/preview/page
```

打開每幅圖所在的完整 PDF 頁與前後頁、長行內代碼頁、第一末頁。逐圖讀完整節點標籤並順箭頭看連接，確認最末節點、長標籤、標題與圖同頁、沒有黑塊／字型缺字／裁邊和不可讀縮圖。正文字詞與圖標籤相同不能借正文充數，長標籤只命中短子串也不算。全頁文字搜尋、SVG bbox、節點計數、截圖成功都只提供定位資訊；空白圖或圖內缺字必須判失敗。

紀錄實際開啟的 PDF SHA、頁碼、各圖完整標籤／箭頭／標題觀察、長代碼折行及前後頁結果。小書檢查全部圖頁；大書可以抽樣一般版面，但逐幅圖的完整性要求不能以抽樣取代。未看完就交代剩餘頁，保持待驗證。
