# Copyright (C) 2026 roundface
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.

"""使用 WinUSB 的 QBraille XL NVDA 點字顯示器驅動程式。

本檔案保留英文 API 名稱與協定術語，並在程式碼旁加入繁體中文說明，方便
日後學習。註解只解釋既有流程，不改變驅動程式行為。

The display speaks the HIMS bulk protocol, but NVDA's built-in HIMS driver
opens legacy endpoint paths (``devicePath\\0`` and ``devicePath\\1``).  Zadig
binds the device to WinUSB, for which the WinUSB user-mode API must be used.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
import winreg

import addonHandler
import bdDetect
import braille
import hwPortUtils
from hwIo.base import Serial
from brailleDisplayDrivers import hims
from logHandler import log


addonHandler.initTranslation()

# 2026.3 的點字基底類別移至新模組；舊版繼續使用原有的公開 API。
try:
	from braille.display.driver import BrailleDisplayDriver as BaseBrailleDisplayDriver
	from braille.constants import AUTOMATIC_PORT
except ModuleNotFoundError as error:
	if error.name not in ("braille.display", "braille.display.driver"):
		raise
	from braille import BrailleDisplayDriver as BaseBrailleDisplayDriver
	from braille import AUTOMATIC_PORT


USB_ID = "VID_045E&PID_930B"
USB_IDS = {"VID_045E&PID_930A", USB_ID}
# 來自使用者提供的 2026.3 hims.py：原廠 hims_winusb.inf 所用的介面。
HIMS_WINUSB_GUID = "{78A1C341-4539-11d3-B88D-00C04FAD5171}"
# 以下常數是 Windows SetupAPI、Kernel32 與 WinUSB API 使用的旗標/錯誤碼。
_USB_REGISTRY_PATH = r"SYSTEM\CurrentControlSet\Enum\USB"
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_DIGCF_PRESENT = 0x2
_DIGCF_DEVICEINTERFACE = 0x10
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_FLAG_OVERLAPPED = 0x40000000
_OPEN_EXISTING = 3
_ERROR_NO_MORE_ITEMS = 259
_ERROR_OPERATION_ABORTED = 995
_ERROR_IO_PENDING = 997
# USBD_PIPE_TYPE: Control=0, Isochronous=1, Bulk=2, Interrupt=3.
_USBD_PIPE_TYPE_BULK = 2


class _GUID(ctypes.Structure):
	"""Windows GUID 的 ctypes 記憶體配置。"""
	_fields_ = (
		("Data1", wintypes.DWORD),
		("Data2", wintypes.WORD),
		("Data3", wintypes.WORD),
		("Data4", ctypes.c_ubyte * 8),
	)


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
	"""SetupAPI 回傳的裝置介面資料。"""
	_fields_ = (
		("cbSize", wintypes.DWORD),
		("InterfaceClassGuid", _GUID),
		("Flags", wintypes.DWORD),
		("Reserved", ctypes.c_void_p),
	)


class _SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
	"""SetupAPI 用來取得實際裝置路徑的資料結構。"""
	_fields_ = (
		("cbSize", wintypes.DWORD),
		("DevicePath", wintypes.WCHAR * 1024),
	)


class _USB_INTERFACE_DESCRIPTOR(ctypes.Structure):
	"""WinUSB 介面描述元，包含端點數量。"""
	_fields_ = (
		("bLength", ctypes.c_ubyte),
		("bDescriptorType", ctypes.c_ubyte),
		("bInterfaceNumber", ctypes.c_ubyte),
		("bAlternateSetting", ctypes.c_ubyte),
		("bNumEndpoints", ctypes.c_ubyte),
		("bInterfaceClass", ctypes.c_ubyte),
		("bInterfaceSubClass", ctypes.c_ubyte),
		("bInterfaceProtocol", ctypes.c_ubyte),
		("iInterface", ctypes.c_ubyte),
	)


class _WINUSB_PIPE_INFORMATION(ctypes.Structure):
	"""USB 端點（pipe）的類型、編號與封包大小。"""
	_fields_ = (
		("PipeType", ctypes.c_int),
		("PipeId", ctypes.c_ubyte),
		("MaximumPacketSize", wintypes.WORD),
		("Interval", ctypes.c_ubyte),
	)


class _OVERLAPPED(ctypes.Structure):
	"""Windows 非同步 I/O 使用的 OVERLAPPED 結構。"""
	_fields_ = (
		("Internal", ctypes.c_size_t),
		("InternalHigh", ctypes.c_size_t),
		("Offset", wintypes.DWORD),
		("OffsetHigh", wintypes.DWORD),
		("hEvent", wintypes.HANDLE),
	)


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_ole32 = ctypes.OleDLL("ole32")
_winusb = ctypes.WinDLL("winusb", use_last_error=True)

_kernel32.CreateFileW.argtypes = (
	wintypes.LPCWSTR,
	wintypes.DWORD,
	wintypes.DWORD,
	ctypes.c_void_p,
	wintypes.DWORD,
	wintypes.DWORD,
	wintypes.HANDLE,
)
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CreateEventW.argtypes = (
	ctypes.c_void_p,
	wintypes.BOOL,
	wintypes.BOOL,
	wintypes.LPCWSTR,
)
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.ResetEvent.argtypes = (wintypes.HANDLE,)
_kernel32.ResetEvent.restype = wintypes.BOOL

_setupapi.SetupDiGetClassDevsW.argtypes = (
	ctypes.POINTER(_GUID),
	wintypes.LPCWSTR,
	wintypes.HWND,
	wintypes.DWORD,
)
_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = (
	wintypes.HANDLE,
	ctypes.c_void_p,
	ctypes.POINTER(_GUID),
	wintypes.DWORD,
	ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
)
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = (
	wintypes.HANDLE,
	ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
	ctypes.POINTER(_SP_DEVICE_INTERFACE_DETAIL_DATA_W),
	wintypes.DWORD,
	ctypes.POINTER(wintypes.DWORD),
	ctypes.c_void_p,
)
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = (wintypes.HANDLE,)
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

_ole32.CLSIDFromString.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(_GUID))
_ole32.CLSIDFromString.restype = ctypes.HRESULT

_winusb.WinUsb_Initialize.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p))
_winusb.WinUsb_Initialize.restype = wintypes.BOOL
_winusb.WinUsb_Free.argtypes = (ctypes.c_void_p,)
_winusb.WinUsb_Free.restype = wintypes.BOOL
_winusb.WinUsb_QueryInterfaceSettings.argtypes = (
	ctypes.c_void_p,
	ctypes.c_ubyte,
	ctypes.POINTER(_USB_INTERFACE_DESCRIPTOR),
)
_winusb.WinUsb_QueryInterfaceSettings.restype = wintypes.BOOL
_winusb.WinUsb_QueryPipe.argtypes = (
	ctypes.c_void_p,
	ctypes.c_ubyte,
	ctypes.c_ubyte,
	ctypes.POINTER(_WINUSB_PIPE_INFORMATION),
)
_winusb.WinUsb_QueryPipe.restype = wintypes.BOOL
_winusb.WinUsb_ReadPipe.argtypes = (
	ctypes.c_void_p,
	ctypes.c_ubyte,
	ctypes.POINTER(ctypes.c_ubyte),
	wintypes.ULONG,
	ctypes.POINTER(wintypes.ULONG),
	ctypes.POINTER(_OVERLAPPED),
)
_winusb.WinUsb_ReadPipe.restype = wintypes.BOOL
_winusb.WinUsb_WritePipe.argtypes = _winusb.WinUsb_ReadPipe.argtypes
_winusb.WinUsb_WritePipe.restype = wintypes.BOOL
_winusb.WinUsb_AbortPipe.argtypes = (ctypes.c_void_p, ctypes.c_ubyte)
_winusb.WinUsb_AbortPipe.restype = wintypes.BOOL
_winusb.WinUsb_GetOverlappedResult.argtypes = (
	ctypes.c_void_p,
	ctypes.POINTER(_OVERLAPPED),
	ctypes.POINTER(wintypes.ULONG),
	wintypes.BOOL,
)
_winusb.WinUsb_GetOverlappedResult.restype = wintypes.BOOL


def _winError(message: str) -> OSError:
	# ctypes 讀取最後一個 Win32 錯誤，轉成帶有可讀訊息的例外。
	return ctypes.WinError(ctypes.get_last_error(), message)


def _findInterfaceGuids() -> list[str]:
	"""讀取 Zadig 為指定 QBraille USB ID 寫入的 WinUSB 介面 GUID。"""
	# Zadig 會把 WinUSB 介面 GUID 寫入登錄檔；先找出 GUID 才能查詢裝置路徑。
	guids: list[str] = [HIMS_WINUSB_GUID]
	try:
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _USB_REGISTRY_PATH) as usbKey:
			index = 0
			while True:
				try:
					deviceName = winreg.EnumKey(usbKey, index)
				except OSError:
					break
				index += 1
				if not any(usbId in deviceName.upper() for usbId in USB_IDS):
					continue
				with winreg.OpenKey(usbKey, deviceName) as deviceKey:
					instanceIndex = 0
					while True:
						try:
							instanceName = winreg.EnumKey(deviceKey, instanceIndex)
						except OSError:
							break
						instanceIndex += 1
						try:
							with winreg.OpenKey(deviceKey, instanceName + r"\Device Parameters") as parametersKey:
								values, _ = winreg.QueryValueEx(parametersKey, "DeviceInterfaceGUIDs")
						except OSError:
							continue
						if isinstance(values, str):
							values = [values]
						guids.extend(value for value in values if value not in guids)
	except OSError:
		log.debugWarning("Could not inspect QBraille WinUSB registry entries", exc_info=True)
	return guids


def _devicePathsForGuid(guidString: str):
	# SetupAPI 依 GUID 列舉目前存在的介面，並篩選 QBraille 的 USB ID。
	guid = _GUID()
	if _ole32.CLSIDFromString(guidString, ctypes.byref(guid)) < 0:
		return
	deviceInfo = _setupapi.SetupDiGetClassDevsW(
		ctypes.byref(guid), None, None, _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE
	)
	if deviceInfo == _INVALID_HANDLE_VALUE:
		raise _winError("SetupDiGetClassDevsW failed")
	try:
		index = 0
		while True:
			interfaceData = _SP_DEVICE_INTERFACE_DATA()
			interfaceData.cbSize = ctypes.sizeof(interfaceData)
			if not _setupapi.SetupDiEnumDeviceInterfaces(
				deviceInfo, None, ctypes.byref(guid), index, ctypes.byref(interfaceData)
			):
				if ctypes.get_last_error() == _ERROR_NO_MORE_ITEMS:
					break
				raise _winError("SetupDiEnumDeviceInterfaces failed")
			index += 1
			detail = _SP_DEVICE_INTERFACE_DETAIL_DATA_W()
			# SetupAPI requires 8 on 64-bit Windows and 6 on 32-bit Windows.
			detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
			if not _setupapi.SetupDiGetDeviceInterfaceDetailW(
				deviceInfo,
				ctypes.byref(interfaceData),
				ctypes.byref(detail),
				ctypes.sizeof(detail),
				None,
				None,
			):
				raise _winError("SetupDiGetDeviceInterfaceDetailW failed")
			if any(usbId.lower() in detail.DevicePath.lower() for usbId in USB_IDS):
				yield detail.DevicePath
	finally:
		_setupapi.SetupDiDestroyDeviceInfoList(deviceInfo)


class _WinUsbTransport:
	"""封裝 WinUSB 控制代碼，提供執行緒安全的讀寫。"""

	def __init__(self, path: str, onReceive):
		# 以 OVERLAPPED 模式開啟介面，讀取工作交由背景執行緒處理。
		self._onReceive = onReceive
		self._stopping = threading.Event()
		self._readEvent = threading.Event()
		self._writeLock = threading.Lock()
		self._handle = _kernel32.CreateFileW(
			path,
			_GENERIC_READ | _GENERIC_WRITE,
			_FILE_SHARE_READ | _FILE_SHARE_WRITE,
			None,
			_OPEN_EXISTING,
			_FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OVERLAPPED,
			None,
		)
		if self._handle == _INVALID_HANDLE_VALUE:
			raise _winError("Could not open the QBraille WinUSB interface")
		self._usbHandle = ctypes.c_void_p()
		try:
			if not _winusb.WinUsb_Initialize(self._handle, ctypes.byref(self._usbHandle)):
				raise _winError("WinUsb_Initialize failed")
			self._findBulkPipes()
		except Exception:
			if self._usbHandle.value:
				_winusb.WinUsb_Free(self._usbHandle)
			_kernel32.CloseHandle(self._handle)
			raise
		self._thread = threading.Thread(target=self._readLoop, name="QBrailleXLWinUSB", daemon=True)
		self._thread.start()

	def _findBulkPipes(self):
		# 顯示器使用一個 Bulk IN（裝置到電腦）和一個 Bulk OUT 端點。
		descriptor = _USB_INTERFACE_DESCRIPTOR()
		if not _winusb.WinUsb_QueryInterfaceSettings(self._usbHandle, 0, ctypes.byref(descriptor)):
			raise _winError("WinUsb_QueryInterfaceSettings failed")
		self._pipeIn = None
		self._pipeOut = None
		self._readSize = 64
		for index in range(descriptor.bNumEndpoints):
			pipe = _WINUSB_PIPE_INFORMATION()
			if not _winusb.WinUsb_QueryPipe(self._usbHandle, 0, index, ctypes.byref(pipe)):
				raise _winError("WinUsb_QueryPipe failed")
			log.info(
				f"QBraille XL WinUSB endpoint {index}: type={pipe.PipeType}, "
				f"id=0x{pipe.PipeId:02X}, maxPacket={pipe.MaximumPacketSize}"
			)
			if pipe.PipeType != _USBD_PIPE_TYPE_BULK:
				continue
			if pipe.PipeId & 0x80:
				self._pipeIn = pipe.PipeId
				self._readSize = max(64, pipe.MaximumPacketSize)
			else:
				self._pipeOut = pipe.PipeId
		if self._pipeIn is None or self._pipeOut is None:
			raise RuntimeError("The QBraille WinUSB interface has no bulk input/output pipe")
		log.info(f"QBraille XL WinUSB pipes: IN=0x{self._pipeIn:02X}, OUT=0x{self._pipeOut:02X}")

	def _readLoop(self):
		# 持續等待裝置資料；停止時由 close() 中止 pipe，讓等待立即結束。
		buffer = (ctypes.c_ubyte * self._readSize)()
		eventHandle = _kernel32.CreateEventW(None, True, False, None)
		if not eventHandle:
			log.error("Could not create the QBraille XL WinUSB read event", exc_info=True)
			return
		try:
			while not self._stopping.is_set():
				if not _kernel32.ResetEvent(eventHandle):
					log.error(f"Could not reset QBraille XL WinUSB read event: {_winError('ResetEvent failed')}")
					return
				overlapped = _OVERLAPPED()
				overlapped.hEvent = eventHandle
				transferred = wintypes.ULONG()
				if not _winusb.WinUsb_ReadPipe(
					self._usbHandle,
					self._pipeIn,
					buffer,
					self._readSize,
					None,
					ctypes.byref(overlapped),
				):
					error = ctypes.get_last_error()
					if error != _ERROR_IO_PENDING:
						if self._stopping.is_set() or error == _ERROR_OPERATION_ABORTED:
							return
						log.error(f"QBraille XL WinUSB read failed: {ctypes.WinError(error)}")
						return
				if not _winusb.WinUsb_GetOverlappedResult(
					self._usbHandle,
					ctypes.byref(overlapped),
					ctypes.byref(transferred),
					True,
				):
					error = ctypes.get_last_error()
					if self._stopping.is_set() or error == _ERROR_OPERATION_ABORTED:
						return
					log.error(f"QBraille XL WinUSB overlapped read failed: {ctypes.WinError(error)}")
					return
				if transferred.value:
					data = bytes(buffer[: transferred.value])
					try:
						self._onReceive(data)
					except Exception:
						log.exception("Error while processing QBraille XL input")
					self._readEvent.set()
		finally:
			_kernel32.CloseHandle(eventHandle)

	def write(self, data: bytes):
		# 每次寫入建立自己的事件；鎖避免多個 NVDA 執行緒同時寫入。
		buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
		transferred = wintypes.ULONG()
		eventHandle = _kernel32.CreateEventW(None, True, False, None)
		if not eventHandle:
			raise _winError("Could not create the QBraille XL WinUSB write event")
		overlapped = _OVERLAPPED()
		overlapped.hEvent = eventHandle
		with self._writeLock:
			try:
				if not _winusb.WinUsb_WritePipe(
					self._usbHandle,
					self._pipeOut,
					buffer,
					len(data),
					None,
					ctypes.byref(overlapped),
				):
					error = ctypes.get_last_error()
					if error != _ERROR_IO_PENDING:
						raise ctypes.WinError(error, "QBraille XL WinUSB write failed")
				if not _winusb.WinUsb_GetOverlappedResult(
					self._usbHandle,
					ctypes.byref(overlapped),
					ctypes.byref(transferred),
					True,
				):
					raise _winError("QBraille XL WinUSB overlapped write failed")
			finally:
				_kernel32.CloseHandle(eventHandle)
		if transferred.value != len(data):
			raise IOError(f"Short WinUSB write: {transferred.value} of {len(data)} bytes")

	def waitForRead(self, timeout: float) -> bool:
		# 初始化時用來等待背景讀取執行緒收到回應。
		result = self._readEvent.wait(timeout)
		self._readEvent.clear()
		return result

	def close(self):
		# 中止讀取、等待執行緒結束，再釋放 WinUSB 與檔案控制代碼。
		if self._stopping.is_set():
			return
		self._stopping.set()
		_winusb.WinUsb_AbortPipe(self._usbHandle, self._pipeIn)
		self._thread.join(1.0)
		_winusb.WinUsb_Free(self._usbHandle)
		_kernel32.CloseHandle(self._handle)


class BrailleDisplayDriver(hims.BrailleDisplayDriver):
	"""以 HIMS 協定處理資料、透過 WinUSB 或藍牙傳輸。"""
	name = "qbrailleXLWinUSB"
	description = _("QBraille XL (WinUSB / Bluetooth)")
	isThreadSafe = True
	supportsAutomaticDetection = True
	timeout = 0.5

	@classmethod
	def check(cls) -> bool:
		"""允許 NVDA 在裝置尚未連線時先啟用自動偵測。"""
		# 即使尚未插入 USB，也要讓 NVDA 註冊藍牙偵測，才能找到稍後連線的裝置。
		return True

	@classmethod
	def matchesBluetoothDevice(cls, match):
		# 原廠手冊：點字 SPP 名稱是 Braille EDGE；QBrailleXL 是另一個鍵盤 HID 連線。
		# 忽略空格與大小寫，以相容 Windows 及不同韌體的顯示名稱。
		name = "".join(match.id.split()).casefold()
		return (
			match.type == bdDetect.ProtocolType.SERIAL
			and "bluetoothName" in match.deviceInfo
			and name.startswith("brailleedge")
		)

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar):
		# 先註冊 USB ID，再把 WinUSB 掃描器移到最前，避免內建 HIMS 驅動搶先開啟。
		driverRegistrar.addUsbDevices(bdDetect.ProtocolType.CUSTOM, USB_IDS)
		driverRegistrar.addBluetoothDevices(cls.matchesBluetoothDevice)
		# The built-in HIMS driver claims the same USB ID and uses legacy
		# ``devicePath\\0`` / ``devicePath\\1`` endpoint handles. When WinUSB is
		# installed, that attempt can leave a partial legacy handle open if its
		# second endpoint fails. Scan this WinUSB interface before the generic USB
		# scanner so our base interface can be opened first.
		driverRegistrar.addDeviceScanner(cls._scanWinUsbDevices, moveToStart=True)

	@classmethod
	def interfaceGuids(cls):
		# 原廠介面已知，先嘗試即可；只有找不到時才讀取 Zadig 的登錄資料。
		yield HIMS_WINUSB_GUID
		for guid in _findInterfaceGuids():
			if guid.casefold() != HIMS_WINUSB_GUID.casefold():
				yield guid

	@classmethod
	def _scanWinUsbDevices(cls, usb=True, bluetooth=False, limitToDevices=None):
		# 將每個找到的 WinUSB 路徑包裝成 NVDA 的 DeviceMatch。
		if limitToDevices and cls.name not in limitToDevices:
			return
		# 先找實際接上的 USB；藍牙埠列舉可能很慢，不能擋住 USB 的啟動。
		# 此函式逐一產生結果，NVDA 成功連線後便停止，不會繼續列舉藍牙。
		seenPaths = set()
		for guidString in cls.interfaceGuids() if usb else ():
			for path in _devicePathsForGuid(guidString):
				# 保留此介面真正的識別碼，避免將 930A 裝置誤報成 930B。
				usbId = next((value for value in USB_IDS if value.lower() in path.lower()), None)
				if usbId is None:
					continue
				# 原廠與登錄檔可能提供同一介面，不要重複開啟同一裝置。
				if path.casefold() in seenPaths:
					continue
				seenPaths.add(path.casefold())
				yield (
					cls.name,
					bdDetect.DeviceMatch(
						bdDetect.ProtocolType.CUSTOM,
						usbId,
						path,
						{"usbID": usbId, "devicePath": path, "interfaceGuid": guidString},
					),
				)
		if bluetooth:
			for match in bdDetect.getPossibleBluetoothDevicesForDriver(cls.name):
				yield cls.name, match

	@classmethod
	def getManualPorts(cls):
		# 自動偵測仍為預設；需要排錯時也能明確指定點字藍牙埠。
		yield AUTOMATIC_PORT
		for match in cls.bluetoothPorts():
			yield match.port, f"{match.id} ({match.port})"

	@classmethod
	def bluetoothPorts(cls):
		# 與 HIMS 的手動序列埠方式相同，但只列出本裝置的 SPP 埠。
		for info in hwPortUtils.listComPorts():
			if "bluetoothName" not in info:
				continue
			match = bdDetect.DeviceMatch(
				bdDetect.ProtocolType.SERIAL, info["bluetoothName"], info["port"], info,
			)
			if cls.matchesBluetoothDevice(match):
				yield match

	@classmethod
	def connectionCandidates(cls, port):
		# 自動偵測傳來的裝置必須直接使用，不能改連其他 USB 或藍牙裝置。
		if isinstance(port, bdDetect.DeviceMatch):
			yield port
			return
		if port not in ("auto", "usb", "bluetooth"):
			for match in cls.bluetoothPorts():
				if match.port.casefold() == port.casefold():
					yield match
			return
		if port in ("auto", "usb"):
			for _, match in cls._scanWinUsbDevices(usb=True):
				yield match
		if port in ("auto", "bluetooth"):
			yield from bdDetect.getPossibleBluetoothDevicesForDriver(cls.name)

	def __init__(self, port="auto"):
		# 自行選擇 WinUSB 與藍牙傳輸；按鍵與點字協定沿用已安裝 NVDA 的 HIMS。
		BaseBrailleDisplayDriver.__init__(self)
		self.numCells = 0
		self._model = None
		self._serialData = b""
		self.isHID = False
		lastError = None
		for match in self.connectionCandidates(port):
			self.numCells = 0
			self._model = None
			self._serialData = b""
			self.isBulk = match.type == bdDetect.ProtocolType.CUSTOM
			dev = None
			try:
				log.info(f"Opening QBraille XL via {match.type} ({match.port})")
				if self.isBulk and match.id in USB_IDS:
					self._dev = dev = _WinUsbTransport(match.port, self._onReceive)
				elif self.matchesBluetoothDevice(match):
					# 使用 NVDA 的 HIMS 序列埠參數與背景 I/O，接收流程沿用 HIMS。
					self._dev = dev = Serial(
						match.port,
						baudrate=hims.BAUD_RATE,
						parity=hims.PARITY,
						timeout=self.timeout,
						writeTimeout=self.timeout,
						onReceive=self._onReceive,
					)
				else:
					continue
				for _attempt in range(3):
					self._sendCellCountRequest()
					# 若快速回應已完成，直接啟用顯示器，不再進入讀取等待。
					if self.numCells:
						break
					# 與參考 HIMS 相同，USB 切換模式後可能需要較長的準備時間。
					dev.waitForRead(self.timeout * 10 if self.isBulk else self.timeout)
					if self.numCells:
						break
				if not self.numCells:
					raise RuntimeError("QBraille XL did not answer the cell-count request")
				if self.numCells != 40:
					raise RuntimeError(f"Expected a 40-cell QBraille XL/Braille EDGE, got {self.numCells}")
				# 原廠手冊確認 USB 與藍牙 SPP 均使用 Braille EDGE 40 協定。
				self._model = hims.BrailleEdge()
				log.info(f"Found QBraille XL via {match.type} ({match.port}) with {self.numCells} cells")
				return
			except Exception as error:
				lastError = error
				log.debugWarning(f"Could not initialize QBraille XL on {match.port}", exc_info=True)
				# 未連線或沒有回應時釋放埠，讓下一次自動偵測能重新嘗試。
				if dev is not None:
					dev.close()
		if lastError:
			raise RuntimeError("QBraille XL USB/Bluetooth connection failed") from lastError
		raise RuntimeError("No QBraille XL found; connect USB WinUSB or pair the Braille EDGE Bluetooth SPP device")
