"""Quick test script for the desktop executor stack.

Run on Windows:  python test_executor.py --logic
Run on Ubuntu VM: python test_executor.py --live
"""

import argparse
import sys


def test_logic():
    """Test all imports, dict sizes, coordinate mapping, and handler lookup.
    Works on any OS — no xdotool needed.
    """
    print("=" * 60)
    print("LOGIC TESTS (no xdotool required)")
    print("=" * 60)
    passed = 0
    failed = 0

    # --- Test 1: settings.py ---
    try:
        from core.settings import (
            UBUNTU_SHORTCUTS, FREECAD_SHORTCUTS,
            EXCLUDED_PREDEFINED_FUNCTIONS,
            SCREEN_WIDTH, SCREEN_HEIGHT,
        )
        assert len(UBUNTU_SHORTCUTS) >= 80, f"Expected 80+ Ubuntu shortcuts, got {len(UBUNTU_SHORTCUTS)}"
        assert len(FREECAD_SHORTCUTS) >= 50, f"Expected 50+ FreeCAD shortcuts, got {len(FREECAD_SHORTCUTS)}"
        assert len(EXCLUDED_PREDEFINED_FUNCTIONS) == 5
        assert SCREEN_WIDTH == 1920
        assert SCREEN_HEIGHT == 1080

        # Check two-key sequences exist
        two_key = [k for k, v in FREECAD_SHORTCUTS.items() if isinstance(v["keys"], list)]
        assert len(two_key) >= 20, f"Expected 20+ two-key sequences, got {len(two_key)}"

        # Check every entry has required fields
        for name, entry in UBUNTU_SHORTCUTS.items():
            assert "keys" in entry, f"Ubuntu shortcut '{name}' missing 'keys'"
            assert "description" in entry, f"Ubuntu shortcut '{name}' missing 'description'"
        for name, entry in FREECAD_SHORTCUTS.items():
            assert "keys" in entry, f"FreeCAD shortcut '{name}' missing 'keys'"
            assert "description" in entry, f"FreeCAD shortcut '{name}' missing 'description'"

        print(f"  [PASS] settings.py — {len(UBUNTU_SHORTCUTS)} Ubuntu + {len(FREECAD_SHORTCUTS)} FreeCAD shortcuts")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] settings.py — {e}")
        failed += 1

    # --- Test 2: screenshot.py import ---
    try:
        from core.screenshot import capture_desktop_screenshot
        assert callable(capture_desktop_screenshot)
        print(f"  [PASS] screenshot.py — function importable")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] screenshot.py — {e}")
        failed += 1

    # --- Test 3: freecad_functions.py imports ---
    try:
        from core.freecad_functions import (
            execute_system_shortcut, execute_freecad_shortcut,
            open_application, type_system_text,
            system_click, right_click, double_click, system_scroll,
        )
        print(f"  [PASS] freecad_functions.py — all 8 functions importable")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] freecad_functions.py — {e}")
        failed += 1

    # --- Test 4: custom_tools.py ---
    try:
        from core.custom_tools import get_custom_declarations, get_excluded_functions

        declarations = get_custom_declarations()
        assert len(declarations) == 5, f"Expected 5 declarations, got {len(declarations)}"

        names = [d.name for d in declarations]
        expected_names = ["system_shortcut", "freecad_shortcut", "right_click_at", "double_click_at", "open_application"]
        assert names == expected_names, f"Declaration names mismatch: {names}"

        excluded = get_excluded_functions()
        assert len(excluded) == 5

        # Check that descriptions contain shortcut listings
        sys_desc = declarations[0].description
        assert "maximize_window" in sys_desc, "system_shortcut description should list shortcuts"
        fc_desc = declarations[1].description
        assert "sketcher_line" in fc_desc, "freecad_shortcut description should list shortcuts"

        print(f"  [PASS] custom_tools.py — 5 declarations, descriptions populated")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] custom_tools.py — {e}")
        failed += 1

    # --- Test 5: desktop_executor.py ---
    try:
        from core.desktop_executor import DesktopExecutor

        executor = DesktopExecutor()
        assert executor.screen_width == 1920
        assert executor.screen_height == 1080
        assert executor.model_width == 1280
        assert executor.model_height == 720

        # Coordinate mapping tests (image pixels -> screen pixels)
        # With 1280x720 model and 1920x1080 screen, scale factor is 1.5x
        sx, sy = executor.to_screen_coords(0, 0)
        assert sx == 0 and sy == 0, f"Origin should map to (0,0), got ({sx},{sy})"

        sx, sy = executor.to_screen_coords(640, 360)
        assert sx == 960 and sy == 540, f"Center should map to (960,540), got ({sx},{sy})"

        sx, sy = executor.to_screen_coords(1280, 720)
        assert sx == 1920 and sy == 1080, f"Max should map to (1920,1080), got ({sx},{sy})"

        # Typical menu click: model x=171 -> screen x=256 (171*1920/1280)
        sx, sy = executor.to_screen_coords(171, 33)
        assert sx == int(171 * 1920 / 1280), f"Menu x mismatch: got {sx}"
        assert sy == int(33 * 1080 / 720), f"Menu y mismatch: got {sy}"

        # Custom screen/model sizes
        executor2 = DesktopExecutor(screen_width=2560, screen_height=1440,
                                    model_width=1280, model_height=720)
        sx, sy = executor2.to_screen_coords(640, 360)
        assert sx == 1280 and sy == 720, f"Custom size center: got ({sx},{sy})"

        # Handler lookup
        for name in ["click_at", "hover_at", "type_text_at", "key_combination",
                      "scroll_at", "scroll_document", "drag_and_drop", "wait_5_seconds",
                      "system_shortcut", "freecad_shortcut", "right_click_at",
                      "double_click_at", "open_application"]:
            handler = executor._get_handler(name)
            assert handler is not None, f"Missing handler for '{name}'"

        # Unknown function returns None
        assert executor._get_handler("nonexistent_function") is None

        print(f"  [PASS] desktop_executor.py — class, to_screen_coords, 13 handlers verified")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] desktop_executor.py — {e}")
        failed += 1

    # --- Summary ---
    print()
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    return failed == 0


def test_live():
    """Live test on Ubuntu VM — actually fires xdotool actions.
    Only run this on the target Ubuntu desktop!
    """
    import platform
    if platform.system() != "Linux":
        print("Live tests require Ubuntu Linux with xdotool. Skipping.")
        return False

    print("=" * 60)
    print("LIVE TESTS (xdotool on Ubuntu)")
    print("=" * 60)
    passed = 0
    failed = 0

    # --- Test 1: Screenshot ---
    try:
        from core.screenshot import capture_desktop_screenshot
        screenshot_bytes = capture_desktop_screenshot()
        assert len(screenshot_bytes) > 1000, "Screenshot too small — likely failed"
        # Check PNG magic bytes
        assert screenshot_bytes[:4] == b'\x89PNG', "Not a valid PNG file"
        print(f"  [PASS] screenshot — captured {len(screenshot_bytes)} bytes")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] screenshot — {e}")
        failed += 1

    # --- Test 2: System shortcut (open terminal) ---
    try:
        from core.freecad_functions import execute_system_shortcut
        import time

        result = execute_system_shortcut("open_terminal")
        assert result.get("success"), f"Failed: {result}"
        print(f"  [PASS] system_shortcut('open_terminal') — terminal should have opened")
        time.sleep(2)

        # Close it
        result = execute_system_shortcut("close_window")
        assert result.get("success"), f"Failed: {result}"
        print(f"  [PASS] system_shortcut('close_window') — terminal should have closed")
        passed += 2
    except Exception as e:
        print(f"  [FAIL] system shortcut — {e}")
        failed += 1

    # --- Test 3: Mouse click at center ---
    try:
        from core.freecad_functions import system_click
        result = system_click(960, 540)
        assert result.get("success"), f"Failed: {result}"
        print(f"  [PASS] system_click(960, 540) — clicked screen center")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] system_click — {e}")
        failed += 1

    # --- Test 4: FreeCAD shortcut (two-key sequence, safe to run even without FreeCAD) ---
    try:
        from core.freecad_functions import execute_freecad_shortcut

        # This is just a keypress test — won't do anything harmful outside FreeCAD
        result = execute_freecad_shortcut("edit_undo")
        assert result.get("success"), f"Failed: {result}"
        print(f"  [PASS] freecad_shortcut('edit_undo') — Ctrl+Z sent")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] freecad_shortcut — {e}")
        failed += 1

    # --- Test 5: Full executor with mock function calls ---
    try:
        from core.desktop_executor import DesktopExecutor

        # Create a mock function call object
        class MockFunctionCall:
            def __init__(self, name, args):
                self.name = name
                self.args = args

        executor = DesktopExecutor()

        # Test hover (safe — just moves mouse)
        calls = [MockFunctionCall("hover_at", {"x": 500, "y": 500})]
        results = executor.execute(calls)
        assert len(results) == 1
        assert results[0][0] == "hover_at"
        assert results[0][1].get("success"), f"Failed: {results[0][1]}"
        print(f"  [PASS] executor.execute(hover_at) — mouse moved to center")
        passed += 1

        # Test unknown function
        calls = [MockFunctionCall("fake_function", {})]
        results = executor.execute(calls)
        assert "error" in results[0][1]
        print(f"  [PASS] executor.execute(unknown) — correctly returned error")
        passed += 1

    except Exception as e:
        print(f"  [FAIL] executor live test — {e}")
        failed += 1

    # --- Summary ---
    print()
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the desktop executor stack")
    parser.add_argument("--logic", action="store_true", help="Run logic-only tests (any OS)")
    parser.add_argument("--live", action="store_true", help="Run live xdotool tests (Ubuntu only)")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    if not (args.logic or args.live or args.all):
        args.logic = True  # Default to logic tests

    success = True
    if args.logic or args.all:
        success = test_logic() and success
    if args.live or args.all:
        success = test_live() and success

    sys.exit(0 if success else 1)
