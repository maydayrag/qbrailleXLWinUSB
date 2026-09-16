# QBraille XL WinUSB NVDA 附加元件

這個附加元件讓 NVDA 透過 Microsoft WinUSB 連接 HIMS QBraille XL，以及使用相同通訊協定的 Braille EDGE 點字顯示器。

## 功能

- 自動偵測 USB `VID_045E&PID_930B` 的相容點字顯示器。
- 支援由 Zadig 安裝的 Microsoft WinUSB 驅動程式。
- 支援點字輸出、游標定位鍵、點字鍵盤與裝置功能鍵。
- 支援 NVDA 2026.1 及 2026.2。
- 提供繁體中文與英文使用說明。

## 安裝

1. 使用 Zadig 將 QBraille XL 的 USB 驅動程式設為 WinUSB。
2. 從 [Releases](https://github.com/maydayrag/qbrailleXLWinUSB/releases) 下載最新的 `.nvda-addon`。
3. 安裝附加元件並完整重新啟動 NVDA。
4. 將 QBraille XL 切換至 USB 模式並連接電腦。
5. NVDA 應會自動偵測裝置；也可在「NVDA 設定 → 點字」選擇「QBraille XL (WinUSB)」。

## 系統需求

- NVDA 2026.1 或更新版本
- Windows 11 AMD64（已在 NVDA 2026.2 實機驗證）
- 以 Zadig 安裝的 WinUSB 裝置驅動程式

## 維護紀錄

開發、除錯與硬體驗證歷程請見 [ISSUE_LOG.md](ISSUE_LOG.md)。所有新問題與修正都必須同步記錄。

## 建置

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

安裝檔會輸出至 `dist/`。
