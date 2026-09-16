# Copyright (C) 2026 QBraille XL WinUSB contributors
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.

"""NVDA braille display driver for a QBraille XL using WinUSB.

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
from brailleDisplayDrivers import hims
from logHandler import log


addonHandler.initTranslation()


USB_ID = "VID_045E&PID_930B"
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
	_fields_ = (
		("Data1", wintypes.DWORD),
		("Data2", wintypes.WORD),
		("Data3", wintypes.WORD),
		("Data4", ctypes.c_ubyte * 8),
	)


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
	_fields_ = (
		("cbSize", wintypes.DWORD),
		("InterfaceClassGuid", _GUID),
		("Flags", wintypes.DWORD),
		("Reserved", ctypes.c_void_p),
	)


class _SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
	_fields_ = (
		("cbSize", wintypes.DWORD),
		("DevicePath", wintypes.WCHAR * 1024),
	)


class _USB_INTERFACE_DESCRIPTOR(ctypes.Structure):
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
	_fields_ = (
		("PipeType", ctypes.c_int),
		("PipeId", ctypes.c_ubyte),
		("MaximumPacketSize", wintypes.WORD),
		("Interval", ctypes.c_ubyte),
	)


class _OVERLAPPED(ctypes.Structure):
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
	return ctypes.WinError(ctypes.get_last_error(), message)


def _findInterfaceGuids() -> list[str]:
	"""Read the interface GUID written by Zadig for the QBraille USB ID."""
	guids: list[str] = []
	try:
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _USB_REGISTRY_PATH) as usbKey:
			index = 0
			while True:
				try:
					deviceName = winreg.EnumKey(usbKey, index)
				except OSError:
					break
				index += 1
				if USB_ID not in deviceName.upper():
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
			if USB_ID.lower() in detail.DevicePath.lower():
				yield detail.DevicePath
	finally:
		_setupapi.SetupDiDestroyDeviceInfoList(deviceInfo)


class _WinUsbTransport:
	def __init__(self, path: str, onReceive):
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
		result = self._readEvent.wait(timeout)
		self._readEvent.clear()
		return result

	def close(self):
		if self._stopping.is_set():
			return
		self._stopping.set()
		_winusb.WinUsb_AbortPipe(self._usbHandle, self._pipeIn)
		self._thread.join(1.0)
		_winusb.WinUsb_Free(self._usbHandle)
		_kernel32.CloseHandle(self._handle)


class BrailleDisplayDriver(hims.BrailleDisplayDriver):
	name = "qbrailleXLWinUSB"
	description = _("QBraille XL (WinUSB)")
	isThreadSafe = True
	supportsAutomaticDetection = True
	timeout = 0.5

	@classmethod
	def check(cls) -> bool:
		"""Expose the driver when the Zadig-created WinUSB interface is installed."""
		return bool(_findInterfaceGuids())

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar):
		driverRegistrar.addUsbDevices(bdDetect.ProtocolType.CUSTOM, {USB_ID})
		# The built-in HIMS driver claims the same USB ID and uses legacy
		# ``devicePath\\0`` / ``devicePath\\1`` endpoint handles. When WinUSB is
		# installed, that attempt can leave a partial legacy handle open if its
		# second endpoint fails. Scan this WinUSB interface before the generic USB
		# scanner so our base interface can be opened first.
		driverRegistrar.addDeviceScanner(cls._scanWinUsbDevices, moveToStart=True)

	@classmethod
	def _scanWinUsbDevices(cls, usb=True, bluetooth=False, limitToDevices=None):
		if not usb or (limitToDevices and cls.name not in limitToDevices):
			return
		for guidString in _findInterfaceGuids():
			for path in _devicePathsForGuid(guidString):
				yield (
					cls.name,
					bdDetect.DeviceMatch(
						bdDetect.ProtocolType.CUSTOM,
						USB_ID,
						path,
						{"usbID": USB_ID, "devicePath": path, "interfaceGuid": guidString},
					),
				)

	@classmethod
	def getManualPorts(cls):
		# Always expose an automatic port so the driver can be selected manually.
		return iter((braille.AUTOMATIC_PORT,))

	def __init__(self, port="auto"):
		# Do not call hims.BrailleDisplayDriver.__init__; it uses legacy bulk endpoint paths.
		braille.BrailleDisplayDriver.__init__(self)
		self.numCells = 0
		self._model = None
		self._serialData = b""
		self.isBulk = True
		self.isHID = False
		lastError = None
		interfaceGuids = _findInterfaceGuids()
		log.info(f"QBraille XL WinUSB interface GUIDs: {interfaceGuids!r}")
		for guidString in interfaceGuids:
			for path in _devicePathsForGuid(guidString):
				log.info(f"Trying QBraille XL WinUSB interface: {path}")
				try:
					self._dev = _WinUsbTransport(path, self._onReceive)
					for _attempt in range(3):
						self._sendCellCountRequest()
						self._dev.waitForRead(self.timeout * 4)
						if self.numCells:
							break
					if not self.numCells:
						raise RuntimeError("QBraille XL did not answer the cell-count request")
					# PID 930B uses the Braille EDGE/QBraille-compatible HIMS protocol.
					self._model = hims.BrailleEdge()
					log.info(f"Found QBraille XL through WinUSB with {self.numCells} cells")
					return
				except Exception as error:
					lastError = error
					log.error("Could not initialize QBraille XL WinUSB interface", exc_info=True)
					if hasattr(self, "_dev"):
						self._dev.close()
		if lastError:
			raise RuntimeError("QBraille XL WinUSB connection failed") from lastError
		raise RuntimeError(
			"QBraille XL WinUSB interface was not found; connect the display and verify the Zadig driver"
		)
