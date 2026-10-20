"""Exercise connection decisions without requiring NVDA or physical hardware.

Compile the actual driver class with fake hardware boundaries. Protocol handling
remains inherited from NVDA HIMS and is not replaced in the shipped add-on.
"""
import ast
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from unittest.mock import patch
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
Match = namedtuple("DeviceMatch", "type id port deviceInfo")


class Base:
    def __init__(self):
        pass

    def _onReceive(self, data):
        pass

    def _sendCellCountRequest(self):
        self._dev.write(b"cell-count")


class Connections(unittest.TestCase):
    def setUp(self):
        self.bt = Match("serial", "Braille EDGE", "COM7", {"bluetoothName": "Braille EDGE"})
        self.usb = Match("custom", "VID_045E&PID_930B", "usb-path", {})
        self.btDevices = Mock(return_value=iter([self.bt]))
        self.serial = Mock()
        self.usbTransport = Mock()
        self.guids = Mock(return_value=["guid"])
        self.ns = {
            "hims": SimpleNamespace(BrailleDisplayDriver=Base, BrailleEdge=Mock(), BAUD_RATE=115200, PARITY="N"),
            "braille": SimpleNamespace(BrailleDisplayDriver=Base, AUTOMATIC_PORT=("auto", "Automatic")),
            "bdDetect": SimpleNamespace(DeviceMatch=Match, DriverRegistrar=object,
                ProtocolType=SimpleNamespace(CUSTOM="custom", SERIAL="serial", HID="hid"),
                getPossibleBluetoothDevicesForDriver=self.btDevices),
            "Serial": self.serial, "_WinUsbTransport": self.usbTransport,
            "_findInterfaceGuids": self.guids,
            "_devicePathsForGuid": Mock(return_value=["usb-path"]),
            "BaseBrailleDisplayDriver": Base,
            "AUTOMATIC_PORT": ("auto", "Automatic"),
            "hwPortUtils": SimpleNamespace(listComPorts=Mock(return_value=[self.bt.deviceInfo | {"port": "COM7"}])),
            "USB_ID": "VID_045E&PID_930B", "_": lambda s: s, "log": Mock(),
        }
        tree = ast.parse((ROOT / "addon/brailleDisplayDrivers/qbrailleXLWinUSB.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BrailleDisplayDriver")
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "driver-under-test", "exec"), self.ns)
        self.driver = self.ns["BrailleDisplayDriver"]

    def responding(self, factory):
        dev = Mock()
        def wait(timeout):
            factory.call_args.kwargs.get("onReceive", factory.call_args.args[-1]).__self__.numCells = 40
        dev.waitForRead.side_effect = wait
        factory.return_value = dev
        return dev

    def test_bluetooth_names_and_exclusion(self):
        for name in ("Braille EDGE", "BrailleEDGE", "braille edge 123"):
            self.assertTrue(self.driver.matchesBluetoothDevice(self.bt._replace(id=name)))
        for match in (self.bt._replace(id="QBrailleXL"), self.bt._replace(type="hid"),
                      self.bt._replace(deviceInfo={}), self.bt._replace(id="Other")):
            self.assertFalse(self.driver.matchesBluetoothDevice(match))

    def test_available_without_usb_and_registers_both(self):
        self.guids.return_value = []
        self.assertTrue(self.driver.check())
        registrar = Mock()
        self.driver.registerAutomaticDetection(registrar)
        registrar.addBluetoothDevices.assert_called_once_with(self.driver.matchesBluetoothDevice)
        registrar.addUsbDevices.assert_called_once_with("custom", {self.usb.id})
        self.assertTrue(registrar.addDeviceScanner.call_args.kwargs["moveToStart"])

    def test_scanner_filters_and_bluetooth_without_usb(self):
        self.assertEqual(list(self.driver._scanWinUsbDevices(usb=False, bluetooth=True)), [(self.driver.name, self.bt)])
        self.guids.assert_not_called()
        self.assertEqual(list(self.driver._scanWinUsbDevices(bluetooth=True, limitToDevices=["other"])), [])

    def test_exact_bluetooth_match_and_serial_settings(self):
        dev = self.responding(self.serial)
        driver = self.driver(self.bt)
        self.usbTransport.assert_not_called()
        self.guids.assert_not_called()
        self.assertFalse(driver.isBulk)
        self.assertEqual(driver.numCells, 40)
        self.assertEqual(self.serial.call_args.args[0], "COM7")
        self.assertEqual(self.serial.call_args.kwargs["baudrate"], 115200)
        self.assertEqual(self.serial.call_args.kwargs["parity"], "N")
        dev.close.assert_not_called()

    def test_usb_uses_winusb_and_exact_path(self):
        self.responding(self.usbTransport)
        driver = self.driver(self.usb)
        self.serial.assert_not_called()
        self.assertTrue(driver.isBulk)
        self.assertEqual(self.usbTransport.call_args.args[0], "usb-path")

    def test_no_response_closes_and_allows_future_retry(self):
        dev = self.serial.return_value
        with self.assertRaises(RuntimeError):
            self.driver(self.bt)
        self.assertEqual(dev.write.call_count, 3)
        dev.close.assert_called_once()
        self.responding(self.serial)
        self.assertEqual(self.driver(self.bt).numCells, 40)

    def test_failed_usb_falls_back_to_bluetooth(self):
        usb = self.usbTransport.return_value
        self.responding(self.serial)
        driver = self.driver("auto")
        usb.close.assert_called_once()
        self.assertFalse(driver.isBulk)
        self.assertEqual(driver.numCells, 40)

    def test_open_failure_and_keyboard_are_rejected(self):
        self.serial.side_effect = OSError("busy")
        with self.assertRaises(RuntimeError):
            self.driver(self.bt)
        self.serial.reset_mock()
        with self.assertRaises(RuntimeError):
            self.driver(self.bt._replace(type="hid", id="QBrailleXL"))
        self.serial.assert_not_called()

    def test_transport_specific_candidates(self):
        self.assertEqual(list(self.driver.connectionCandidates("bluetooth")), [self.bt])
        self.guids.assert_not_called()
        self.btDevices.reset_mock()
        self.assertEqual([m.port for m in self.driver.connectionCandidates("usb")], ["usb-path"])
        self.btDevices.assert_not_called()

    def test_manual_bluetooth_port_and_unknown_port(self):
        self.assertEqual(list(self.driver.getManualPorts()), [("auto", "Automatic"), ("COM7", "Braille EDGE (COM7)")])
        self.responding(self.serial)
        self.assertEqual(self.driver("com7").numCells, 40)
        self.assertEqual(list(self.driver.connectionCandidates("COM99")), [])
        self.usbTransport.assert_not_called()

    def test_usb_waits_for_mode_switch(self):
        dev = self.responding(self.usbTransport)
        self.driver(self.usb)
        dev.waitForRead.assert_called_once_with(5.0)

    def test_incompatible_cell_count_releases_port(self):
        dev = self.serial.return_value
        def wait(timeout):
            self.serial.call_args.kwargs["onReceive"].__self__.numCells = 32
        dev.waitForRead.side_effect = wait
        with self.assertRaises(RuntimeError):
            self.driver(self.bt)
        dev.close.assert_called_once()

    def test_duplicate_usb_paths_are_scanned_once(self):
        self.guids.return_value = ["vendor", "zadig"]
        matches = list(self.driver._scanWinUsbDevices())
        self.assertEqual(len(matches), 1)

    def test_vendor_guid_available_without_zadig_registry(self):
        tree = ast.parse((ROOT / "addon/brailleDisplayDrivers/qbrailleXLWinUSB.py").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_findInterfaceGuids")
        registry = SimpleNamespace(HKEY_LOCAL_MACHINE=0, OpenKey=Mock(side_effect=OSError("missing")))
        ns = {"winreg": registry, "_USB_REGISTRY_PATH": "USB", "log": Mock(), "HIMS_WINUSB_GUID": "vendor-guid"}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "guid-under-test", "exec"), ns)
        self.assertEqual(ns["_findInterfaceGuids"](), ["vendor-guid"])

    def test_new_and_old_api_import_paths(self):
        tree = ast.parse((ROOT / "addon/brailleDisplayDrivers/qbrailleXLWinUSB.py").read_text(encoding="utf-8"))
        block = next(n for n in tree.body if isinstance(n, ast.Try))
        code = compile(ast.Module(body=[block], type_ignores=[]), "imports-under-test", "exec")
        for modern in (False, True):
            braille = ModuleType("braille")
            braille.BrailleDisplayDriver = Base
            braille.AUTOMATIC_PORT = ("auto", "Automatic")
            modules = {"braille": braille, "braille.display": None, "braille.display.driver": None}
            if modern:
                braille.__path__ = []
                display = ModuleType("braille.display")
                display.__path__ = []
                driver = ModuleType("braille.display.driver")
                driver.BrailleDisplayDriver = Base
                constants = ModuleType("braille.constants")
                constants.AUTOMATIC_PORT = ("auto", "Automatic")
                modules.update({"braille.display": display, "braille.display.driver": driver, "braille.constants": constants})
            with patch.dict(sys.modules, modules):
                ns = {}
                exec(code, ns)
                self.assertIs(ns["BaseBrailleDisplayDriver"], Base)
                self.assertEqual(ns["AUTOMATIC_PORT"][0], "auto")


if __name__ == "__main__":
    unittest.main()
