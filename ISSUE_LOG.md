# QBraille XL WinUSB issue log

This file is the permanent maintenance record for defects, investigation
results, and fixes. Update it whenever a new problem is reported or a fix is
changed. Do not mark an issue as verified on hardware until an NVDA log or a
device test confirms the result.

## Issue template

- Version reported:
- Status: investigating / fixed, awaiting hardware verification / verified
- Symptom and relevant log entry:
- Root cause:
- Change made:
- Verification:
- Follow-up:

## 2026-10-21 — 2.0 bug-fix release

- Status: automated checks passed; physical-device verification pending.
- Evidence: compared the user-supplied root-level `hims.py` with the required
  NVDA 2026.2 source, Developer Guide and Add-on Development Guide. The
  reference supplies the manufacturer's WinUSB GUID and longer bulk startup
  wait. Public base-driver and constant import locations were also checked
  against NVDA source.
- Fixes: scan the vendor WinUSB GUID as well as Zadig registry GUIDs; remove
  duplicate paths; extend USB startup waits; select the available base-driver
  API and import automatic-port constants directly; expose matching Bluetooth
  COM ports for troubleshooting; reject non-40-cell responses.
- Compatibility: `lastTestedNVDAVersion` remains `2026.2`; this release does not
  claim additional NVDA runtime or device tests.
- Validation: 15 isolated tests and final archive integrity/source checks.
  Tests simulate hardware and both import layouts; they do not prove device
  operation in a live NVDA process.

## 2026-10-03 — Bluetooth SPP support in 1.5

- Version: 1.5
- Status: implemented, awaiting Bluetooth hardware verification
- Previous behavior: availability depended on WinUSB registry entries and the
  constructor scanned USB regardless of NVDA's detected device.
- Evidence: manufacturer's QBraille XL manual sections 4.1–4.3 identify
  `Braille EDGE` as the braille SPP device and `QBrailleXL` as keyboard HID;
  both braille connections use the Braille EDGE 40 protocol. NVDA 2026.2
  `brailleDisplayDrivers/hims.py` supplies serial settings, input/output and
  termination; `hwIo/base.py` supplies background serial I/O; `bdDetect.py`
  supplies Bluetooth matching, device-change scanning and app-switch retries.
  Developer Guide plugin layout and Add-on Development Guide driver sections
  were also reviewed.
- Change: register serial-only Bluetooth matching; include Bluetooth in the
  existing priority scanner; expose the driver without USB; honor exact
  DeviceMatch; use NVDA Serial for SPP and WinUSB for USB; close failed
  handshakes. Keep the existing add-on ID for upgrade compatibility.
- Verification: nine isolated automated tests cover names/HID rejection,
  registration, scan filters, exact-device handling, serial settings, USB,
  timeout cleanup, retry, busy ports and USB-to-Bluetooth fallback. Final
  package verification checks ZIP signature/CRC, version, driver location,
  syntax and exact source/documentation bytes.
- Follow-up: test real Bluetooth pairing, braille output/input/routing,
  disconnect/reconnect and USB regression under NVDA 2026.2. Automated tests
  use fake transports and do not prove radio or physical-device behavior.

## 2026-09-16 — Add-on installs but NVDA does not discover the driver

- Version reported: 0.1.0
- Status: fixed and verified by the 0.1.1 NVDA import attempt
- Symptom: NVDA loaded `noBraille`; there was no import or initialization log
  for `qbrailleXLWinUSB`.
- Root cause: the installation archive contained
  `addon/brailleDisplayDrivers/qbrailleXLWinUSB.py`. NVDA add-on archives must
  contain `brailleDisplayDrivers/qbrailleXLWinUSB.py` at the archive root.
- Change made: corrected the archive layout and added `build.ps1` so source
  layout and installation layout are handled separately.
- Verification: NVDA subsequently imported the driver from
  `addons/qbrailleXLWinUSB/brailleDisplayDrivers/qbrailleXLWinUSB.py`.

## 2026-09-16 — Driver import fails because `wintypes.HRESULT` is unavailable

- Version reported: 0.1.1
- Status: fixed and verified by the next NVDA run
- Symptom: `AttributeError: module 'ctypes.wintypes' has no attribute
  'HRESULT'` while importing the driver.
- Root cause: Python 3.13 exposes this Windows result type as
  `ctypes.HRESULT`, not `ctypes.wintypes.HRESULT`.
- Change made: changed the `CLSIDFromString` return type to `ctypes.HRESULT`.
- Verification: later NVDA logs imported and initialized the driver without
  this exception.

## 2026-09-16 — Add-on translation was not initialized

- Version found during review: 0.1.1
- Status: fixed and verified by import testing
- Symptom: after fixing `HRESULT`, evaluation of the translated driver
  description would have failed because `_` was not initialized for the
  add-on module.
- Root cause: the module did not call `addonHandler.initTranslation()`.
- Change made: imported `addonHandler` and initialized translations before
  evaluating translatable strings.
- Verification: isolated module import test completed and returned the driver
  name and description.

## 2026-09-16 — Driver is excluded before automatic detection registration

- Version reported: 0.1.3
- Status: fixed and verified by registry and scanner tests
- Symptom: Windows showed the connected device, but NVDA remained on
  `noBraille` and never called the driver constructor.
- Root cause: the inherited availability check depended on NVDA automatic
  detection data before this driver had registered that data. Manual ports
  were also empty, so NVDA excluded the driver from the supported-driver
  enumeration.
- Change made: `check()` now tests the Zadig-created WinUSB interface GUID
  directly. The driver also always exposes NVDA's `auto` port.
- Verification: the installed device was found as `VID_045E&PID_930B`, using
  service `WinUSB`, with interface GUID
  `{8245F072-EFA5-4659-A433-5D2F67EAC00C}`. Local checks returned `True` and
  exposed the automatic port.

## 2026-09-16 — Built-in HIMS driver competes for the same USB ID

- Version reported: 0.1.5
- Status: fixed; automatic scan order verified, hardware connection pending
- Symptom: NVDA recognized the USB ID but the custom WinUSB driver did not get
  a clean first attempt.
- Root cause: NVDA's built-in HIMS driver also registers
  `VID_045E&PID_930B`. It uses legacy `devicePath\\0` and `devicePath\\1`
  endpoint paths, which are not the correct WinUSB access method. Its legacy
  bulk constructor can also leave the first handle open if opening the second
  endpoint fails.
- Change made: registered a public `bdDetect` device scanner with
  `moveToStart=True`, yielding the WinUSB driver and exact interface path
  before the generic USB scanner.
- Verification: the custom scanner yields the expected `DeviceMatch`, and
  later NVDA logs show `qbrailleXLWinUSB` being initialized automatically.

## 2026-09-16 — WinUSB interface open originally returned access denied

- Versions investigated: 0.1.4 and 0.1.5
- Status: mitigated; superseded by the more precise 0.1.6/0.1.7 findings
- Symptom: an isolated test made while NVDA was running returned WinError 5
  while opening the device.
- Root cause: more than one factor was possible: the built-in HIMS attempt
  could compete for the same device, and a running older add-on repeatedly
  rescanned the device. The test was not performed with NVDA fully stopped.
- Change made: WinUSB is tried before HIMS, `FILE_SHARE_READ` and
  `FILE_SHARE_WRITE` are used, and testing instructions require a complete
  NVDA restart between versions.
- Verification: in the 0.1.6 NVDA log, `CreateFileW` succeeded and execution
  reached `WinUsb_Initialize`, proving that access denied was no longer the
  active failure in that run.

## 2026-09-16 — `WinUsb_Initialize` returns WinError 6

- Version reported: 0.1.6
- Status: fixed in 0.1.7, awaiting hardware verification
- Symptom: `OSError: [WinError 6] WinUsb_Initialize failed`.
- Root cause: WinUSB requires the device file handle to be opened with
  `FILE_FLAG_OVERLAPPED`. The driver had opened it for synchronous I/O.
- Change made: opened the interface with `FILE_ATTRIBUTE_NORMAL |
  FILE_FLAG_OVERLAPPED`; converted `WinUsb_ReadPipe` and `WinUsb_WritePipe` to
  overlapped operations using event handles and
  `WinUsb_GetOverlappedResult`; added cancellation and failure cleanup.
- Verification: Python syntax and package layout pass. Hardware verification
  requires the NVDA log from the first run after installing 0.1.7.

## 2026-09-16 — WinUSB reports no bulk input/output pipe

- Version reported: 0.1.7
- Status: fixed in 0.1.8 and verified with the physical display
- Symptom: `RuntimeError: The QBraille WinUSB interface has no bulk
  input/output pipe` after `WinUsb_Initialize` succeeded.
- Root cause: the driver incorrectly defined `USBD_PIPE_TYPE_BULK` as `3`.
  The Windows `USBD_PIPE_TYPE` values are Control `0`, Isochronous `1`, Bulk
  `2`, and Interrupt `3`. Consequently, valid bulk endpoints were ignored.
- Change made: corrected the bulk pipe type to `2` and added an INFO log for
  every endpoint containing its type, endpoint ID, and maximum packet size.
- Verification: version 0.1.8 started normally and successfully connected to
  the physical QBraille XL. The user confirmed that the problem was resolved.

## 2026-09-16 — Version 1.0 release

- Status: verified and released
- Result: the complete WinUSB discovery, overlapped I/O, endpoint selection,
  HIMS protocol initialization, braille output and input path were verified by
  successfully starting the physical QBraille XL with NVDA 2026.2.
- Release changes: promoted the add-on to version 1.0 and added Traditional
  Chinese manifest metadata, documentation, and repository introduction.

## Environmental messages not caused by this add-on

- WorldVoice reports a missing Cerence `ve.dll`. This is a WorldVoice engine
  installation problem and is unrelated to QBraille XL or WinUSB.
- NVDA Remote warns that certificate verification is skipped for the selected
  relay. This is unrelated to the braille driver.
