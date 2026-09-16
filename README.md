# QBraille XL WinUSB NVDA Add-on

This add-on connects HIMS QBraille XL displays, and Braille EDGE displays
using the same communication protocol, to NVDA through Microsoft WinUSB.

## Features

- Automatically detects compatible displays with USB ID `VID_045E&PID_930B`.
- Supports the Microsoft WinUSB driver installed by Zadig.
- Supports braille output, routing keys, braille keyboard input, and display
  function keys.
- Supports NVDA 2026.1 and 2026.2.
- Includes English and Traditional Chinese documentation.

## Installation

1. Use Zadig to install the WinUSB driver for the QBraille XL.
2. Download the latest `.nvda-addon` package from [Releases](https://github.com/maydayrag/qbrailleXLWinUSB/releases).
3. Install the add-on and fully restart NVDA.
4. Switch the QBraille XL to USB mode and connect it to the computer.
5. NVDA should detect the display automatically. You can also select
   **QBraille XL (WinUSB)** under **NVDA Settings → Braille**.

## Requirements

- NVDA 2026.1 or later
- Windows 11 AMD64 (verified with NVDA 2026.2)
- The WinUSB device driver installed with Zadig
