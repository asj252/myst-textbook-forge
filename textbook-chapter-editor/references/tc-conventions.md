# 繁體中文教材的語言慣例

適用範圍：用本 skill 編輯的繁體中文教材內容（正文、小結、練習與解答）。

## 內容語言

繁體中文（台灣用語）。

## 行／列

**行 = column，列 = row**（與簡體中文相反），全書嚴格遵守。

以英文概念與公式／代碼錨點為準：

| 英文概念 | 公式／代碼錨點 | 繁體中文寫法 |
|---|---|---|
| row $i$ | $\text{row}_i(\mathbf{A})$、`A[i, :]` | 第 $i$ 列 |
| column $j$ | $\text{col}_j(\mathbf{A})$、`A[:, j]` | 第 $j$ 行 |
| row vector | $1\times n$ | 列向量 |
| column vector | $n\times 1$ | 行向量 |
| row space | $\text{Row}(\mathbf{A})$ | 列空間 |
| column space | $\text{Col}(\mathbf{A})$ | 行空間 |
| (elementary) row operation | 左乘初等矩陣 | （基本）列運算 |
| (elementary) column operation | 右乘初等矩陣 | （基本）行運算 |
| $m\times n$ matrix | $m$ rows, $n$ columns | $m$ 列 $n$ 行 |

Code cell 的注釋、字串與輸出同樣採用本慣例（例：`# 用第0列（row 0）展開`）。

拿不準某個「行」「列」指的是哪一個方向時，先回到上表的英文概念或公式錨點（$\text{row}_i(\mathbf{A})$ 表示第 $i$ 列，$\text{col}_j(\mathbf{A})$ 表示第 $j$ 行），再決定中文寫法。

不帶方向義、不受上表影響的詞：行列式、行為、進行、執行、平行、排列、序列、雙行記法；「cell 內行號」的「行」指程式碼或文字的 line。

## 序數

統一使用阿拉伯數字，與 0-based 索引保持視覺一致：「第 0 列」（row 0）、「第 2 行」（column 2），不寫「第零列」。
