"""Standalone entry point for the HomeKit accessory bridge subprocess.

Run as `python -m app.tbc.homekit_worker <config.json>`, spawned by
HomeKitManager (app/tbc/homekit.py). Kept in its own OS process rather than a
thread inside the main app - see homekit.py's module docstring for why.

Config file (written by HomeKitManager.start()) is a flat JSON object:
{"persist_file": str, "status_file": str, "port": int, "pincode": "xxx-xx-xxx",
 "cameras": [{"aid": int, "name": str, "stream_uri": str, "snapshot_path": str|None}]}
"""
from __future__ import annotations

import json
import signal
import sys

from pyhap import util as pyhap_util
from pyhap.accessory import Bridge
from pyhap.accessory_driver import AccessoryDriver

from .homekit import TBCCameraAccessory


def main(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)

    address = pyhap_util.get_local_address()
    driver = AccessoryDriver(
        address=address,
        port=int(config["port"]),
        persist_file=config["persist_file"],
        pincode=config["pincode"].encode("ascii"),
    )
    bridge = Bridge(driver, "TBC")
    for camera in config["cameras"]:
        bridge.add_accessory(
            TBCCameraAccessory(
                driver,
                camera["name"],
                aid=camera["aid"],
                stream_uri=camera["stream_uri"],
                snapshot_path=camera.get("snapshot_path"),
                address=address,
            )
        )
    # Loads persisted pairing state (keys, MAC, paired clients) if the
    # persist file already exists, or creates it - synchronous, done before
    # driver.start()'s event loop takes over (see pyhap.AccessoryDriver.
    # add_accessory).
    driver.add_accessory(bridge)

    with open(config["status_file"], "w", encoding="utf-8") as handle:
        json.dump({"pincode": config["pincode"], "xhm_uri": bridge.xhm_uri()}, handle)

    # Maps SIGTERM (what HomeKitManager.stop() sends via Popen.terminate())
    # onto the exact KeyboardInterrupt handling driver.start() already
    # implements for a clean shutdown, instead of a custom shutdown path.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    driver.start()


if __name__ == "__main__":
    main(sys.argv[1])
