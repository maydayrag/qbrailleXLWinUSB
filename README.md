# QBraille XL USB and Bluetooth NVDA Add-on

Version **1.5** connects HIMS QBraille XL and compatible Braille EDGE displays
to NVDA through USB WinUSB or Bluetooth serial (SPP). The add-on identifier
remains `qbrailleXLWinUSB`, so it updates existing installations.

[Download 1.5](https://github.com/maydayrag/qbrailleXLWinUSB/releases/download/v1.5/qbrailleXLWinUSB-1.5.nvda-addon)
| [繁體中文使用說明](doc/zh_TW/readme.html)

## Features

- Automatic USB detection for `VID_045E&PID_930B` with Zadig WinUSB.
- Automatic Bluetooth SPP detection for `Braille EDGE` / `BrailleEDGE` devices.
- Braille output, routing keys, braille keyboard input and display function keys
  through NVDA's HIMS protocol implementation.
- NVDA 2026.1 or later; implementation checked against NVDA 2026.2 source.
- English and Traditional Chinese documentation.

## Install

1. Install the add-on and fully restart NVDA.
2. In NVDA Settings → Braille → Change display, select **Automatic**.
   If automatic detection is restricted to specific displays, include
   **QBraille XL (WinUSB / Bluetooth)**.
3. Set up either connection below. NVDA's background detection opens the
   display once it is available and responds. No manual COM port selection
   is required. You may also select **QBraille XL (WinUSB / Bluetooth)** with
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

## Troubleshooting

- Confirm NVDA is using **Automatic** detection and this driver is allowed.
- For Bluetooth, verify the **Braille EDGE** SPP pairing and COM port,
  select the correct computer connection on the display, and close other
  screen readers that may hold the same port. An offline paired display is
  not treated as connected: it must answer the cell-count request.
- NVDA scans on device changes and retries known Bluetooth devices when
  applications change. If it has not connected yet, switch applications or
  reselect Automatic. Detection is asynchronous; another active display
  continues to use NVDA's normal display selection behavior.
- For USB, check WinUSB and hardware ID `VID_045E&PID_930B` in Device Manager.
- Fully restart NVDA after updating to release old driver handles.
- For unresolved problems, enable NVDA debug logging and provide a complete
  log containing `qbrailleXLWinUSB` and the connection failure.

## Changes in 1.5

- Added Bluetooth SPP automatic detection and serial transport.
- Made the driver available before USB insertion, allowing Bluetooth-only use.
- Honor the exact device supplied by NVDA detection; close unsuccessful
  connections before retrying.
- Updated English and Traditional Chinese installation and troubleshooting.

Automated tests cover detection, transport selection, response timeouts,
cleanup and package integrity. Bluetooth hardware testing is still pending.

## Development

Run `python -m unittest discover -s tests -v`, then `powershell -File build.ps1`,
then `python tests/verify_package.py dist/qbrailleXLWinUSB-1.5.nvda-addon`.

References: [manufacturer's QBraille XL manual, sections 4.1–4.3](https://selvasblv.com/wp-content/resources/qbraille-xl/QBraille%20XL%20User%20Manual%20Rev%20181212.pdf)
and NVDA 2026.2 `brailleDisplayDrivers/hims.py`, `bdDetect.py`, `hwIo/base.py`.

Licensed under GPL; see [COPYING](COPYING).
