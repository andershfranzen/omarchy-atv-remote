import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / "bin" / "discovery.py"
SPEC = importlib.util.spec_from_file_location("discovery", MODULE_PATH)
discovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discovery)


class DiscoveryTests(unittest.TestCase):
    def test_decodes_utf8_avahi_escapes(self):
        self.assertEqual(discovery.decode_avahi(r"K\195\184kken\032TV"), "Køkken TV")

    def test_uses_stable_identifier_and_deduplicates(self):
        line = '=;eth0;IPv4;Living Room;_airplay._tcp;local;host;10.0.0.5;7000;"model=AppleTV14,1" "deviceid=aa:bb"'
        devices = discovery.parse_services(f"{line}\n{line}\n")
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["identifier"], "AA:BB")
        self.assertEqual(devices[0]["address"], "10.0.0.5")

    def test_ignores_non_apple_devices(self):
        line = '=;eth0;IPv4;Speaker;_airplay._tcp;local;host;10.0.0.8;7000;"model=AudioAccessory1,1" "deviceid=aa:cc"'
        self.assertEqual(discovery.parse_services(line), [])


if __name__ == "__main__":
    unittest.main()
