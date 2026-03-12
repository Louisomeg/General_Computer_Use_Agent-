"""Quick test script for the desktop executor stack.

Run on Windows:  python test_executor.py --logic
Run on Ubuntu VM: python test_executor.py --live
"""

import argparse
import sys


def test_logic():
    """Test all imports, coordinate mapping, and handler lookup.
    Works on any OS — no xdotool needed.
    """
    print("=" * 60)
    print("LOGIC TESTS (no xdotool required)")
    print("=" * 60)
    passed = 0
    failed = 0

    # --- Test 1: settings.py ---
    try:
        from core.settings import SCREEN_WIDTH, SCREEN_HEIGHT
        assert SCREEN_WIDTH == 1280
        assert SCREEN_HEIGHT == 800
        print(f"  [PASS] settings.py — screen {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
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
            open_application, system_click, system_hover,
            right_click, double_click, system_scroll,
        )
        print(f"  [PASS] freecad_functions.py — all 6 functions importable")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] freecad_functions.py — {e}")
        failed += 1

    # --- Test 4: custom_tools.py ---
    try:
        from core.custom_tools import get_custom_declarations

        declarations = get_custom_declarations()
        names = [d.name for d in declarations]
        # After shortcut + open_application removal, only GUI-action declarations remain:
        # right_click_at, double_click_at
        expected_names = ["right_click_at", "double_click_at"]
        assert names == expected_names, f"Declaration names mismatch: expected {expected_names}, got {names}"

        print(f"  [PASS] custom_tools.py — {len(declarations)} declarations: {names}")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] custom_tools.py — {e}")
        failed += 1

    # --- Test 5: desktop_executor.py ---
    try:
        from core.desktop_executor import DesktopExecutor

        executor = DesktopExecutor()
        assert executor.screen_width == 1280
        assert executor.screen_height == 800

        # Denormalize tests: 0-1000 normalized → actual screen pixels
        sx, sy = executor.denormalize(0, 0)
        assert sx == 0 and sy == 0, f"Origin should map to (0,0), got ({sx},{sy})"

        sx, sy = executor.denormalize(500, 500)
        assert sx == 640 and sy == 400, f"Center should map to (640,400), got ({sx},{sy})"

        sx, sy = executor.denormalize(999, 999)
        expected_x = int(999 / 1000 * 1280)  # 1278
        expected_y = int(999 / 1000 * 800)    # 799
        assert sx == expected_x and sy == expected_y, \
            f"Max should map to ({expected_x},{expected_y}), got ({sx},{sy})"

        # Custom screen size (e.g. 1440x900 recommended)
        executor2 = DesktopExecutor(screen_width=1440, screen_height=900)
        sx, sy = executor2.denormalize(500, 500)
        assert sx == 720 and sy == 450, f"Custom center: got ({sx},{sy})"

        # Handler lookup (11 handlers — no open_application)
        for name in ["click_at", "hover_at", "type_text_at", "key_combination",
                      "scroll_at", "scroll_document", "drag_and_drop", "wait_5_seconds",
                      "right_click_at", "double_click_at",
                      "task_complete"]:
            handler = executor._get_handler(name)
            assert handler is not None, f"Missing handler for '{name}'"

        # Unknown function returns None
        assert executor._get_handler("nonexistent_function") is None

        print(f"  [PASS] desktop_executor.py — class, denormalize, 11 handlers verified")
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
        assert screenshot_bytes[:4] == b'\x89PNG', "Not a valid PNG file"
        print(f"  [PASS] screenshot — captured {len(screenshot_bytes)} bytes")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] screenshot — {e}")
        failed += 1

    # --- Test 2: Mouse click at center ---
    try:
        from core.freecad_functions import system_click
        result = system_click(640, 400)
        assert result.get("success"), f"Failed: {result}"
        print(f"  [PASS] system_click(640, 400) — clicked screen center")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] system_click — {e}")
        failed += 1

    # --- Test 3: Full executor with mock function calls ---
    try:
        from core.desktop_executor import DesktopExecutor

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
