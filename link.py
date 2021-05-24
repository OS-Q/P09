
import copy
import json
import os
import platform

from platformio.managers.platform import PlatformBase
from platformio.util import get_systype


class P411Platform(PlatformBase):

    def is_embedded(self):
        return True

    def configure_default_packages(self, variables, targets):
        upload_protocol = ""
        board = variables.get("board")
        frameworks = variables.get("pioframework", [])
        if board:
            upload_protocol = variables.get(
                "upload_protocol",
                self.board_config(board).get("upload.protocol", ""))

            if self.board_config(board).get("build.bsp.name",
                                            "nrf5") == "adafruit":
                self.frameworks["arduino"][
                    "package"] = "A411"

            if "mbed" in frameworks:
                deprecated_boards_file = os.path.join(
                    self.get_dir(), "misc", "mbed_deprecated_boards.json")
                if os.path.isfile(deprecated_boards_file):
                    with open(deprecated_boards_file) as fp:
                        if board in json.load(fp):
                            self.packages["framework-mbed"]["version"] = "~6.51506.0"
                self.packages["toolchain-gccarmnoneeabi"]["version"] = "~1.90201.0"

            if "zephyr" in frameworks:
                for p in self.packages:
                    if p.startswith("framework-zephyr-") or p in (
                        "tool-cmake",
                        "tool-dtc",
                        "tool-ninja",
                    ):
                        self.packages[p]["optional"] = False
                self.packages["toolchain-gccarmnoneeabi"]["version"] = "~1.80201.0"
                if "windows" not in get_systype():
                    self.packages["tool-gperf"]["optional"] = False

            if board == "nano33ble":
                self.packages["toolchain-gccarmnoneeabi"]["version"] = "~1.80201.0"
                self.frameworks["arduino"]["package"] = "framework-arduino-mbed"
                self.frameworks["arduino"][
                    "script"
                ] = "builder/frameworks/arduino/mbed-core/arduino-core-mbed.py"

        if set(["bootloader", "erase"]) & set(targets):
            self.packages["tool-nrfjprog"]["optional"] = False
        elif (upload_protocol and upload_protocol != "nrfjprog"
              and "tool-nrfjprog" in self.packages):
            del self.packages["tool-nrfjprog"]

        # configure J-LINK tool
        jlink_conds = [
            "jlink" in variables.get(option, "")
            for option in ("upload_protocol", "debug_tool")
        ]
        if board:
            board_config = self.board_config(board)
            jlink_conds.extend([
                "jlink" in board_config.get(key, "")
                for key in ("debug.default_tools", "upload.protocol")
            ])
        jlink_pkgname = "tool-jlink"
        if not any(jlink_conds) and jlink_pkgname in self.packages:
            del self.packages[jlink_pkgname]

        return PlatformBase.configure_default_packages(self, variables,
                                                       targets)

    def get_boards(self, id_=None):
        result = PlatformBase.get_boards(self, id_)
        if not result:
            return result
        if id_:
            return self._add_default_debug_tools(result)
        else:
            for key, value in result.items():
                result[key] = self._add_default_debug_tools(result[key])
        return result

    def _add_default_debug_tools(self, board):
        debug = board.manifest.get("debug", {})
        upload_protocols = board.manifest.get("upload", {}).get(
            "protocols", [])
        if "tools" not in debug:
            debug["tools"] = {}

        # J-Link / ST-Link / BlackMagic Probe
        for link in ("blackmagic", "jlink", "stlink", "cmsis-dap"):
            if link not in upload_protocols or link in debug['tools']:
                continue

            if link == "blackmagic":
                debug["tools"]["blackmagic"] = {
                    "hwids": [["0x1d50", "0x6018"]],
                    "require_debug_port": True
                }

            elif link == "jlink":
                assert debug.get("jlink_device"), (
                    "Missed J-Link Device ID for %s" % board.id)
                debug["tools"][link] = {
                    "server": {
                        "package": "tool-jlink",
                        "arguments": [
                            "-singlerun",
                            "-if", "SWD",
                            "-select", "USB",
                            "-device", debug.get("jlink_device"),
                            "-port", "2331"
                        ],
                        "executable": ("JLinkGDBServerCL.exe"
                                       if platform.system() == "Windows" else
                                       "JLinkGDBServer")
                    }
                }

            else:
                server_args = [
                    "-s", "$PACKAGE_DIR/scripts",
                    "-f", "interface/%s.cfg" % link
                ]
                if link == "stlink":
                    server_args.extend([
                        "-c",
                        "transport select hla_swd; set WORKAREASIZE 0x4000"
                    ])
                server_args.extend(["-f", "target/nrf52.cfg"])
                debug["tools"][link] = {
                    "server": {
                        "package": "tool-openocd",
                        "executable": "bin/openocd",
                        "arguments": server_args
                    }
                }
                server_args.extend(debug.get("openocd_extra_args", []))

            debug["tools"][link]["onboard"] = link in debug.get("onboard_tools", [])
            debug["tools"][link]["default"] = link in debug.get("default_tools", [])

        board.manifest['debug'] = debug
        return board

    def configure_debug_options(self, initial_debug_options, ide_data):
        debug_options = copy.deepcopy(initial_debug_options)
        adapter_speed = initial_debug_options.get("speed")
        if adapter_speed:
            server_options = debug_options.get("server") or {}
            server_executable = server_options.get("executable", "").lower()
            if "openocd" in server_executable:
                debug_options["server"]["arguments"].extend(
                    ["-c", "adapter speed %s" % adapter_speed]
                )
            elif "jlink" in server_executable:
                debug_options["server"]["arguments"].extend(
                    ["-speed", adapter_speed or "4000"]
                )

        return debug_options
