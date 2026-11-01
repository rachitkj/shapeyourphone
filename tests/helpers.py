import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from shape.adb import Device  # noqa: E402
from shape.state import PhoneState  # noqa: E402
from fakephone import FakePhone  # noqa: E402


class PhoneTest(unittest.TestCase):
    """Each test gets a fresh fake phone and an empty SHAPE_HOME."""

    sdk = 34

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shape-test-")
        self._old_home = os.environ.get("SHAPE_HOME")
        os.environ["SHAPE_HOME"] = self.tmp
        self.phone = FakePhone(sdk=self.sdk)
        self.dev = Device(self.phone.serial, runner=self.phone.runner)
        self.ps = PhoneState(self.dev)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("SHAPE_HOME", None)
        else:
            os.environ["SHAPE_HOME"] = self._old_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, pkg):
        return self.phone.pkgs[pkg]["state"]
