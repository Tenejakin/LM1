import importlib
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BlessCompatibilityTests(unittest.TestCase):
    def test_ble_module_uses_bless_030_writeable_permission(self) -> None:
        readable = object()
        writeable = object()

        class FakePermissions:
            pass

        FakePermissions.readable = readable
        FakePermissions.writeable = writeable

        fake_bless = ModuleType("bless")
        fake_bless.BlessGATTCharacteristic = object
        fake_bless.BlessServer = object
        fake_bless.GATTAttributePermissions = FakePermissions
        fake_bless.GATTCharacteristicProperties = object

        with patch.dict(sys.modules, {"bless": fake_bless}):
            sys.modules.pop("pinpoint_ble", None)
            pinpoint_ble = importlib.import_module("pinpoint_ble")

        self.assertIs(pinpoint_ble.COMMAND_PERMISSIONS, writeable)
        self.assertIs(pinpoint_ble.EVENT_PERMISSIONS, readable)


if __name__ == "__main__":
    unittest.main()
