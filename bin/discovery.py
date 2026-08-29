#!/usr/bin/env python3
"""Parse Apple TV services from Avahi's machine-readable output."""

import json
import re
import subprocess
import sys


def decode_avahi(value):
    raw = bytearray()
    index = 0
    while index < len(value):
        match = re.match(r"\\(\d{3})", value[index:])
        if match:
            raw.append(int(match.group(1)))
            index += 4
        else:
            raw.extend(value[index].encode())
            index += 1
    return raw.decode("utf-8", errors="replace")


def parse_services(output):
    result = []
    seen = set()
    for line in output.splitlines():
        fields = line.split(";", 9)
        if len(fields) < 10 or fields[0] != "=" or fields[2] != "IPv4":
            continue
        name, address, txt = fields[3], fields[7], fields[9]
        model = re.search(r'"model=([^" ]+)', txt)
        device_id = re.search(r'"deviceid=([^" ]+)', txt, re.IGNORECASE)
        if not model or not model.group(1).startswith("AppleTV") or not device_id:
            continue
        stable_id = device_id.group(1).upper()
        if stable_id in seen:
            continue
        seen.add(stable_id)
        result.append({"name": decode_avahi(name), "identifier": stable_id,
                       "deviceIdentifier": stable_id, "address": address,
                       "model": model.group(1)})
    return result


def main():
    try:
        scan = subprocess.run(["avahi-browse", "-rtp", "_airplay._tcp"],
                              capture_output=True, text=True, timeout=8, check=False)
    except FileNotFoundError:
        print(json.dumps({"error": "avahi-browse is not installed", "devices": []}))
        return 127
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "Apple TV discovery timed out", "devices": []}))
        return 1
    devices = parse_services(scan.stdout)
    error = "" if scan.returncode == 0 or devices else (scan.stderr.strip() or "Apple TV discovery failed")
    print(json.dumps({"error": error, "devices": devices}))
    return 0 if not error else 1


if __name__ == "__main__":
    sys.exit(main())
