# QBraille XL / Braille EDGE 點字顯示器驅動程式

**相容 NVDA 2026.1～2026.2。NVDA 2026.3 已內建點字顯示器驅動程式，不需安裝本附加元件。**

**Compatible with NVDA 2026.1–2026.2. NVDA 2026.3 includes the driver; this add-on is not required.**

Version **2.0** connects HIMS QBraille XL and compatible Braille EDGE displays
to NVDA through USB WinUSB or Bluetooth serial (SPP).

[Download 2.0](https://github.com/maydayrag/qbrailleXLWinUSB/releases/download/v2.0/qbrailleXLWinUSB-2.0.nvda-addon)
| [繁體中文使用說明](doc/zh_TW/readme.html)

## Features

- Automatically detects QBraille XL / Braille EDGE.
- Compatible with NVDA 2026.1–2026.2.
- English and Traditional Chinese documentation.

## Install

1. Install the add-on and fully restart NVDA.
2. In NVDA Settings → Braille → Change display, select **Automatic**.
   If automatic detection is restricted to specific displays, include
   **QBraille XL / Braille EDGE 點字顯示器驅動程式**.
3. Set up either connection below. NVDA's background detection opens the
   display once it is available and responds. No manual COM port selection
   is required. You may also select **QBraille XL / Braille EDGE 點字顯示器驅動程式** with
   its **Automatic** port to try currently available connections.

### Bluetooth

1. On QBraille XL, open **Connectivity → Bluetooth Braille** to enter pairing
   mode. For an existing pairing, select the computer's Braille connection.
2. Pair **Braille EDGE** in Windows Bluetooth settings. If Windows asks for
   a PIN, the manufacturer's manual specifies `0000`.
3. Ensure Windows has created a Bluetooth serial (SPP) COM port and the
   display is powered on and available. NVDA opens that port automatically.

The manufacturer uses **Braille EDGE** for the braille SPP connection and
**QBrailleXL** for the separate keyboard HID connection. Pairing only the
keyboard does not provide braille output. Bluetooth does not require Zadig.
Hybrid keyboard operation requires the separate keyboard pairing.

### USB

1. Use Zadig to install Microsoft **WinUSB** for the QBraille XL USB device.
2. Switch the display to USB mode and connect it to the computer.

## Development

Run `python -m unittest discover -s tests -v`, then `powershell -File build.ps1`,
then `python tests/verify_package.py dist/qbrailleXLWinUSB-2.0.nvda-addon`.

Licensed under GPL; see [COPYING](COPYING).
