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


if __name__ == "__main__":
    unittest.main()
