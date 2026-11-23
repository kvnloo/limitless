"""focus_safe.classify: a shell command that drives the owner's foreground UI is a warn, everything else ok.
Synthetic serials and display ids only."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import focus_safe as fs  # noqa: E402

OWNER = "SYNTHETIC0001"      # the owner's phone (protected)
AGENT = "SYNTHETIC0002"      # an agent emulator (not protected)
CFG = {"serials": [OWNER], "agent_displays": ["7", ":99"]}


def verdict(cmd, tool="terminal", **cfg):
    return fs.classify(tool, {"command": cmd}, **(cfg or CFG))


class Inert(unittest.TestCase):
    def test_no_config_is_ok_with_the_reason(self):
        self.assertEqual(fs.classify("terminal", {"command": "adb shell input tap 5 5"}),
                         {"verdict": "ok", "why": "no protected devices set"})

    def test_empty_lists_are_inert(self):
        self.assertEqual(verdict("xdotool key ctrl+l", serials=[], agent_displays=[])["verdict"], "ok")


class Adb(unittest.TestCase):
    def test_input_on_the_owner_phone_warns(self):
        for sub in ("tap 5 5", "swipe 1 2 3 4", "text hello", "keyevent HOME"):
            self.assertEqual(verdict(f"adb -s {OWNER} shell input {sub}")["verdict"], "warn", sub)

    def test_quoted_shell_command_is_read(self):
        self.assertEqual(verdict(f"adb -s {OWNER} shell 'input tap 5 5'")["verdict"], "warn")

    def test_am_start_on_the_owner_phone_warns(self):
        self.assertEqual(verdict(f"adb -s {OWNER} shell am start -n a.b/.Main")["verdict"], "warn")

    def test_an_agent_display_is_ok(self):
        self.assertEqual(verdict(f"adb -s {OWNER} shell am start --display 7 -n a.b/.Main")["verdict"], "ok")
        self.assertEqual(verdict(f"adb -s {OWNER} shell input -d 7 tap 5 5")["verdict"], "ok")

    def test_the_default_display_or_an_unlisted_one_warns(self):
        self.assertEqual(verdict(f"adb -s {OWNER} shell am start --display 0 -n a.b/.Main")["verdict"], "warn")
        self.assertEqual(verdict(f"adb -s {OWNER} shell input -d 3 tap 5 5")["verdict"], "warn")

    def test_another_serial_is_ok(self):
        self.assertEqual(verdict(f"adb -s {AGENT} shell input tap 5 5")["verdict"], "ok")
        self.assertEqual(verdict(f"ANDROID_SERIAL={AGENT} adb shell input tap 5 5")["verdict"], "ok")

    def test_no_serial_may_pick_the_owner_phone(self):
        self.assertEqual(verdict("adb shell input tap 5 5")["verdict"], "warn")
        self.assertEqual(verdict(f"ANDROID_SERIAL={OWNER} adb shell input tap 5 5")["verdict"], "warn")

    def test_read_only_commands_are_ok(self):
        for cmd in ("shell dumpsys window", "shell uiautomator dump /sdcard/u.xml", "exec-out screencap -d 7 -p",
                    "shell getprop", "devices", "logcat -d", "shell"):
            self.assertEqual(verdict(f"adb -s {OWNER} {cmd}")["verdict"], "ok", cmd)

    def test_a_chained_command_is_read_segment_by_segment(self):
        self.assertEqual(verdict(f"adb -s {OWNER} shell dumpsys window; adb -s {OWNER} shell input tap 5 5")
                         ["verdict"], "warn")
        self.assertEqual(verdict(f"cd /tmp && adb -s {OWNER} shell input keyevent HOME")["verdict"], "warn")


class Desktop(unittest.TestCase):
    def test_xdotool_driving_warns(self):
        for cmd in ("xdotool key ctrl+l", "xdotool type hello", "xdotool mousemove 5 5 click 1",
                    "xdotool search --name Editor windowactivate"):
            self.assertEqual(verdict(cmd)["verdict"], "warn", cmd)

    def test_xdotool_on_an_agent_display_is_ok(self):
        self.assertEqual(verdict("DISPLAY=:99 xdotool key ctrl+l")["verdict"], "ok")
        self.assertEqual(verdict("export DISPLAY=:99; xdotool type hello")["verdict"], "ok")

    def test_xdotool_reads_are_ok(self):
        for cmd in ("xdotool getactivewindow", "xdotool getmouselocation", "xdotool search --name Editor"):
            self.assertEqual(verdict(cmd)["verdict"], "ok", cmd)

    def test_wmctrl_activate_warns(self):
        self.assertEqual(verdict("wmctrl -a Editor")["verdict"], "warn")
        self.assertEqual(verdict("wmctrl -l")["verdict"], "ok")
        self.assertEqual(verdict("DISPLAY=:99 wmctrl -a Editor")["verdict"], "ok")

    def test_osascript_activate_or_keystroke_warns(self):
        self.assertEqual(verdict("osascript -e 'tell application \"Notes\" to activate'")["verdict"], "warn")
        self.assertEqual(verdict("osascript -e 'tell application \"System Events\" to keystroke \"a\"'")
                         ["verdict"], "warn")
        self.assertEqual(verdict("osascript -e 'return name of current user'")["verdict"], "ok")

    def test_open_a_warns_unless_in_the_background(self):
        self.assertEqual(verdict("open -a Notes")["verdict"], "warn")
        self.assertEqual(verdict("open -g -a Notes")["verdict"], "ok")
        self.assertEqual(verdict("open -ga Notes")["verdict"], "ok")
        self.assertEqual(verdict("open notes.txt")["verdict"], "ok")

    def test_cliclick_warns(self):
        self.assertEqual(verdict("cliclick c:5,5")["verdict"], "warn")


class Shape(unittest.TestCase):
    def test_only_shell_like_tools_are_read(self):
        self.assertEqual(fs.classify("read_file", {"command": "xdotool key a"}, **CFG)["verdict"], "ok")
        self.assertEqual(fs.classify("terminal", {"cmd": "xdotool key a"}, **CFG)["verdict"], "warn")

    def test_odd_args_are_ok(self):
        for args in (None, {}, {"command": 5}, {"command": "echo 'unclosed"}, "xdotool key a"):
            self.assertEqual(fs.classify("terminal", args, **CFG)["verdict"], "ok", args)

    def test_a_why_is_plain_and_names_no_serial_or_display(self):
        for cmd in (f"adb -s {OWNER} shell input tap 5 5", "adb shell am start --display 3 -n a.b/.M",
                    "xdotool key a", "open -a Notes", "cliclick c:5,5", "wmctrl -a X", "osascript -e activate"):
            why = verdict(cmd)["why"]
            self.assertTrue(why, cmd)
            self.assertNotIn("SYNTHETIC", why)
            self.assertEqual(re.findall(r"\d", why), [], (cmd, why))

    def test_the_rule_table_is_readable(self):
        self.assertTrue(fs.RULES)
        for r in fs.RULES:
            self.assertEqual(set(r), {"id", "drives", "ok_when", "why"}, r)


if __name__ == "__main__":
    unittest.main()
