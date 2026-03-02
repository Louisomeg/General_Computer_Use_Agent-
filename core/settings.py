# =============================================================================
# General Engineering Agent — Settings & Configuration
# =============================================================================

# Actual screen dimensions (Ubuntu VM) — used for xdotool coordinate mapping.
# Google recommends 1440x900 for the Computer Use model.  The closest
# available VM resolution is 1280x800 (same 16:10 aspect ratio).
# IMPORTANT: Change these if you change the VM display resolution.
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 800

# Screenshot resolution sent to the model.
# Set equal to SCREEN dimensions for 1:1 pixel mapping (no resize needed).
# If different from SCREEN, screenshots are resized before sending to the model.
# Must maintain the same aspect ratio as SCREEN to avoid distortion.
MODEL_SCREEN_WIDTH = 1280
MODEL_SCREEN_HEIGHT = 800

# Timing constants (seconds unless noted)
ACTION_DELAY = 1.0              # Pause after each action for UI settling (FreeCAD is slow)
TYPING_DELAY = 50               # Milliseconds between keystrokes (xdotool --delay)
SHORTCUT_DELAY = 0.8            # Pause after a keyboard shortcut (FreeCAD needs time to react)
FREECAD_SEQUENCE_DELAY = 0.3    # Pause between keys in a FreeCAD two-key sequence (e.g. G→R)
APP_LAUNCH_DELAY = 3.0          # Pause after launching an application
SEARCH_TYPE_DELAY = 2.0         # Pause after typing in Ubuntu launcher (needs time to index)
CLICK_DELAY = 0.5               # Pause after a mouse click (FreeCAD UI updates are slow)

# Screenshot
SCREENSHOT_PATH = "/tmp/agent_screenshot.png"

# Predefined Gemini functions to exclude (browser-only, not needed for desktop)
EXCLUDED_PREDEFINED_FUNCTIONS = [
    "open_web_browser",
    "navigate",
    "search",
    "go_back",
    "go_forward",
]

# =============================================================================
# SYSTEM INSTRUCTION — teaches the agent how to use the desktop environment
# =============================================================================

SYSTEM_INSTRUCTION = f"""You are an engineering desktop agent operating on an Ubuntu Linux machine
with a GNOME desktop environment.

## Environment Details
- OS: Ubuntu Linux with GNOME Shell
- Display server: X11 (xdotool is available for all input actions)
- Desktop: GNOME with Activities overview, top bar, and application grid

## PRIMARY INTERACTION METHOD — GUI (click, type, scroll)
You are a VISUAL agent. Always interact with the desktop by looking at the screenshot
and clicking on buttons, menus, icons, and text fields that you can SEE.

Your primary tools are:
- click_at(x, y) — click on visible buttons, menus, icons, taskbar items
- type_text_at(x, y, text) — click a field and type into it
- scroll_at / scroll_document — scroll content
- hover_at — hover over elements
- right_click_at — open context menus
- double_click_at — open files/folders

ALWAYS look at the screenshot first, identify what you see, and click on visible
UI elements to accomplish your goal. This is how a human uses a computer.

## When to Use Shortcuts (ONLY as exceptions)
Keyboard shortcuts (system_shortcut, freecad_shortcut, key_combination) should ONLY
be used in these specific cases:
- open_freecad -- to launch freecad in particular(use it first, before using open_application)
- open_application — to launch apps (this is a helper, use it first to open apps)
- freecad_shortcut("edit_undo") — Ctrl+Z to undo mistakes in FreeCAD
- key_combination("escape") — to cancel the active tool in FreeCAD
- key_combination — for text editing (Ctrl+A, Ctrl+C, Ctrl+V, Enter)
- system_shortcut("minimize_window") — to minimize the terminal at startup

For FreeCAD: use the MENU BAR for ALL operations (geometry, constraints, pad, pocket,
close sketch, view changes). Menus are reliable. Keyboard shortcuts are NOT because
they depend on which panel has focus.

Do NOT use system_shortcut for navigation (switching windows, activities overview, etc.).
Instead, look at the screenshot and:
- Click on windows visible in the taskbar at the top/bottom to switch to them
- Click on the "Activities" text in the top-left corner to open the overview
- Click on application icons in the dock/taskbar to launch or focus them

## How to Open Applications — Step by Step
If you need to open an application, follow these steps IN ORDER. Move to the next
step ONLY if the previous one did not work.

Step 1: Use open_freecad() or open_application("AppName"), then wait_5_seconds.
        Look at the screenshot — did a new window appear? If yes, you're done.

Step 2: Look at the TASKBAR (the bar at the very top of the screen).
        It shows the names/icons of running applications.
        If you see the app name there, CLICK on it to bring its window to front.

Step 3: Click "Activities" text in the TOP-LEFT corner of the screen (coordinates
        roughly x=30, y=10). This opens the GNOME Activities overview.
        - You will see a search bar at the top center and open window thumbnails.
        - Click the search bar and type the app name using type_text_at.
        - Wait for search results to appear below.
        - CLICK on the application icon in the search results (do NOT press Enter).

Step 4: If search shows nothing, look for the "Show Applications" grid icon.
        It is a grid of dots at the BOTTOM of the left dock/sidebar
        (approximately x=15, y=980). Click it to open the full application grid.
        - This shows ALL installed applications as a grid of icons with labels.
        - Scroll down if needed to find the app.
        - CLICK on the application icon to launch it.

Step 5: If you still can't find it, the application may not be installed.
        Report this to the user and stop.

IMPORTANT: At each step, LOOK at the screenshot to verify what happened before
moving to the next step. Never skip steps or assume something worked without checking.

## Coordinate System
- Coordinates use a NORMALIZED 0-1000 grid for both X and Y.
- (0, 0) = top-left corner of the screen.
- (500, 500) = center of the screen.
- (999, 999) = bottom-right corner of the screen.
- The system automatically converts these to actual screen pixels.
- Look at the screenshot carefully to estimate where UI elements are located.

## Action Guidelines
- ALWAYS study the screenshot before every action. Describe what you see.
- After opening an application, use wait_5_seconds to let it fully load.
- Click on menus, buttons, and icons that you can see in the screenshot.
- If a click doesn't work, look at the screenshot again — you may have
  clicked the wrong coordinates. Adjust and try a nearby position.
- If something is not working after 3 attempts with different approaches, stop and report.
- Do NOT blindly repeat the same action — always re-examine the screenshot.

## FreeCAD-Specific
- FreeCAD has: menu bar (top), toolbars, 3D viewport (center),
  model tree (left panel), properties panel (bottom-left), Python console (bottom).
- ALWAYS use the MENU BAR for ALL FreeCAD operations. Click the menu TEXT
  (e.g. "Sketch", "Part Design", "View") — menus are large and easy to click.
- AVOID clicking small toolbar icons — they are ~24px wide and easy to misclick.
- AVOID keyboard shortcuts in FreeCAD — they depend on which panel has keyboard
  focus and can silently fail. Only use Escape (cancel tool) and Ctrl+Z (undo).
- Use menus for everything: sketcher tools (Sketch → Sketcher geometries),
  constraints (Sketch → Sketcher constraints), Part Design operations
  (Part Design → Pad, Pocket, Create sketch), view changes (View menu).
- When FreeCAD first opens, you may see a Start page. Click "Create New..." to begin.

## Important Rules
- Do NOT use browser-related functions (navigate, search, go_back, go_forward).
- ALWAYS observe the screenshot carefully before acting.
- PREFER clicking visible UI elements over keyboard shortcuts.
- If something is not working after 3 attempts, describe the problem and stop.
- Report what you see and what you did clearly to the user.
"""


# =============================================================================
# UBUNTU DESKTOP SHORTCUTS (86 entries)
# Each entry: {"keys": "xdotool key string", "description": "human-readable"}
# =============================================================================

UBUNTU_SHORTCUTS = {

    # ---- Window Management ----
    "maximize_window": {
        "keys": "super+Up",
        "description": "Maximize the current window",
    },
    "unmaximize_window": {
        "keys": "super+Down",
        "description": "Restore/unmaximize window to previous size",
    },
    "minimize_window": {
        "keys": "super+h",
        "description": "Minimize (hide) the current window",
    },
    "close_window": {
        "keys": "alt+F4",
        "description": "Close the current window",
    },
    "snap_window_left": {
        "keys": "super+Left",
        "description": "Snap window to the left half of screen",
    },
    "snap_window_right": {
        "keys": "super+Right",
        "description": "Snap window to the right half of screen",
    },
    "toggle_maximize": {
        "keys": "alt+F10",
        "description": "Toggle maximize/restore for current window",
    },
    "move_window_interactive": {
        "keys": "alt+F7",
        "description": "Enter move mode (arrow keys to move, Enter to confirm)",
    },
    "resize_window_interactive": {
        "keys": "alt+F8",
        "description": "Enter resize mode (arrow keys to resize, Enter to confirm)",
    },
    "window_menu": {
        "keys": "alt+space",
        "description": "Open the window menu (minimize, maximize, close, etc.)",
    },
    "move_window_to_monitor_left": {
        "keys": "shift+super+Left",
        "description": "Move current window one monitor to the left",
    },
    "move_window_to_monitor_right": {
        "keys": "shift+super+Right",
        "description": "Move current window one monitor to the right",
    },
    "toggle_fullscreen": {
        "keys": "F11",
        "description": "Toggle fullscreen mode for the current window",
    },

    # ---- System ----
    "lock_screen": {
        "keys": "super+l",
        "description": "Lock the screen",
    },
    "logout_dialog": {
        "keys": "ctrl+alt+Delete",
        "description": "Show power off / log out dialog",
    },
    "open_terminal": {
        "keys": "ctrl+alt+t",
        "description": "Open a new terminal window",
    },
    "open_file_manager": {
        "keys": "super+e",
        "description": "Open the default file manager (Nautilus)",
    },
    "open_settings": {
        "keys": "super+s",
        "description": "Open system settings / quick settings panel",
    },
    "open_notification_list": {
        "keys": "super+v",
        "description": "Show the notification list / calendar tray",
    },
    "open_notification_area": {
        "keys": "super+m",
        "description": "Toggle the notification/message area",
    },
    "run_command_dialog": {
        "keys": "alt+F2",
        "description": "Open the run command dialog",
    },

    # ---- Clipboard / Editing (Universal) ----
    "copy": {
        "keys": "ctrl+c",
        "description": "Copy selected content to clipboard",
    },
    "paste": {
        "keys": "ctrl+v",
        "description": "Paste content from clipboard",
    },
    "cut": {
        "keys": "ctrl+x",
        "description": "Cut selected content to clipboard",
    },
    "select_all": {
        "keys": "ctrl+a",
        "description": "Select all content",
    },
    "undo": {
        "keys": "ctrl+z",
        "description": "Undo the last action",
    },
    "redo": {
        "keys": "ctrl+shift+z",
        "description": "Redo the last undone action",
    },
    "find": {
        "keys": "ctrl+f",
        "description": "Open find/search dialog",
    },
    "find_and_replace": {
        "keys": "ctrl+h",
        "description": "Open find and replace dialog",
    },
    "save": {
        "keys": "ctrl+s",
        "description": "Save the current document",
    },
    "save_as": {
        "keys": "ctrl+shift+s",
        "description": "Save the current document with a new name",
    },
    "quit_application": {
        "keys": "ctrl+q",
        "description": "Quit the current application",
    },

    # ---- Desktop / Workspace Navigation ----
    "activities_overview": {
        "keys": "super",
        "description": "Toggle the Activities overview (app launcher/search)",
    },
    "show_all_applications": {
        "keys": "super+a",
        "description": "Show the full application grid",
    },
    "switch_application_forward": {
        "keys": "super+Tab",
        "description": "Switch between open applications (forward)",
    },
    "switch_application_backward": {
        "keys": "super+shift+Tab",
        "description": "Switch between open applications (backward)",
    },
    "switch_window_forward": {
        "keys": "alt+Tab",
        "description": "Switch between open windows (forward)",
    },
    "switch_window_backward": {
        "keys": "alt+shift+Tab",
        "description": "Switch between open windows (backward)",
    },
    "switch_windows_same_app": {
        "keys": "super+grave",
        "description": "Switch between windows of the same application",
    },
    "cycle_windows_current_workspace": {
        "keys": "alt+Escape",
        "description": "Cycle through all windows in the current workspace",
    },
    "switch_workspace_up": {
        "keys": "super+Prior",
        "description": "Switch to the workspace above (previous)",
    },
    "switch_workspace_down": {
        "keys": "super+Next",
        "description": "Switch to the workspace below (next)",
    },
    "move_window_to_workspace_up": {
        "keys": "shift+super+Prior",
        "description": "Move current window to the workspace above",
    },
    "move_window_to_workspace_down": {
        "keys": "shift+super+Next",
        "description": "Move current window to the workspace below",
    },
    "focus_top_bar": {
        "keys": "ctrl+alt+Tab",
        "description": "Give keyboard focus to the top bar for navigation",
    },
    "show_desktop": {
        "keys": "super+d",
        "description": "Minimize all windows and show desktop",
    },

    # ---- Screenshots ----
    "screenshot_full": {
        "keys": "Print",
        "description": "Launch the screenshot tool (capture entire screen)",
    },
    "screenshot_window": {
        "keys": "alt+Print",
        "description": "Take a screenshot of the current window",
    },
    "screenshot_area": {
        "keys": "shift+Print",
        "description": "Take a screenshot of a selected area",
    },
    "screencast_toggle": {
        "keys": "shift+ctrl+alt+r",
        "description": "Start or stop screencast recording",
    },

    # ---- Terminal-Specific ----
    "terminal_copy": {
        "keys": "ctrl+shift+c",
        "description": "Copy selected text in terminal",
    },
    "terminal_paste": {
        "keys": "ctrl+shift+v",
        "description": "Paste text in terminal",
    },
    "terminal_new_tab": {
        "keys": "ctrl+shift+t",
        "description": "Open a new tab in terminal",
    },
    "terminal_close_tab": {
        "keys": "ctrl+shift+w",
        "description": "Close the current terminal tab",
    },
    "terminal_new_window": {
        "keys": "ctrl+shift+n",
        "description": "Open a new terminal window",
    },
    "terminal_find": {
        "keys": "ctrl+shift+f",
        "description": "Find text in terminal output",
    },
    "terminal_zoom_in": {
        "keys": "ctrl+shift+plus",
        "description": "Zoom in (increase font size) in terminal",
    },
    "terminal_zoom_out": {
        "keys": "ctrl+shift+minus",
        "description": "Zoom out (decrease font size) in terminal",
    },
    "terminal_fullscreen": {
        "keys": "F11",
        "description": "Toggle fullscreen mode in terminal",
    },
    "terminal_clear_screen": {
        "keys": "ctrl+l",
        "description": "Clear the terminal screen",
    },
    "terminal_interrupt": {
        "keys": "ctrl+c",
        "description": "Interrupt/cancel the currently running command",
    },
    "terminal_search_history": {
        "keys": "ctrl+r",
        "description": "Reverse search through command history",
    },
    "terminal_exit": {
        "keys": "ctrl+d",
        "description": "Exit the terminal (EOF / logout)",
    },
    "terminal_suspend_process": {
        "keys": "ctrl+z",
        "description": "Suspend the current foreground process",
    },

    # ---- File Manager (Nautilus) ----
    "file_manager_toggle_hidden": {
        "keys": "ctrl+h",
        "description": "Show or hide hidden files in Nautilus",
    },
    "file_manager_new_tab": {
        "keys": "ctrl+t",
        "description": "Open a new tab in Nautilus",
    },
    "file_manager_close_tab": {
        "keys": "ctrl+w",
        "description": "Close the current tab in Nautilus",
    },
    "file_manager_new_folder": {
        "keys": "ctrl+shift+n",
        "description": "Create a new folder",
    },
    "file_manager_rename": {
        "keys": "F2",
        "description": "Rename the selected file or folder",
    },
    "file_manager_search": {
        "keys": "ctrl+f",
        "description": "Search in the current folder",
    },
    "file_manager_location_bar": {
        "keys": "ctrl+l",
        "description": "Focus the location/path bar for manual path entry",
    },
    "file_manager_parent_directory": {
        "keys": "alt+Up",
        "description": "Navigate to the parent directory",
    },
    "file_manager_go_back": {
        "keys": "alt+Left",
        "description": "Navigate back in directory history",
    },
    "file_manager_go_forward": {
        "keys": "alt+Right",
        "description": "Navigate forward in directory history",
    },
    "file_manager_bookmark": {
        "keys": "ctrl+d",
        "description": "Bookmark the current location",
    },
    "file_manager_icon_view": {
        "keys": "ctrl+1",
        "description": "Switch to icon view",
    },
    "file_manager_list_view": {
        "keys": "ctrl+2",
        "description": "Switch to list view",
    },
    "file_manager_toggle_sidebar": {
        "keys": "F9",
        "description": "Show or hide the sidebar panel",
    },
    "file_manager_trash": {
        "keys": "Delete",
        "description": "Move selected files to trash",
    },

    # ---- Text Editing / Cursor Navigation ----
    "cursor_to_line_start": {
        "keys": "Home",
        "description": "Move cursor to the beginning of the current line",
    },
    "cursor_to_line_end": {
        "keys": "End",
        "description": "Move cursor to the end of the current line",
    },
    "cursor_to_document_start": {
        "keys": "ctrl+Home",
        "description": "Move cursor to the beginning of the document",
    },
    "cursor_to_document_end": {
        "keys": "ctrl+End",
        "description": "Move cursor to the end of the document",
    },
    "cursor_word_left": {
        "keys": "ctrl+Left",
        "description": "Move cursor one word to the left",
    },
    "cursor_word_right": {
        "keys": "ctrl+Right",
        "description": "Move cursor one word to the right",
    },
    "select_word_left": {
        "keys": "ctrl+shift+Left",
        "description": "Select one word to the left",
    },
    "select_word_right": {
        "keys": "ctrl+shift+Right",
        "description": "Select one word to the right",
    },
    "select_to_line_start": {
        "keys": "shift+Home",
        "description": "Select from cursor to the beginning of the line",
    },
    "select_to_line_end": {
        "keys": "shift+End",
        "description": "Select from cursor to the end of the line",
    },
    "delete_word_left": {
        "keys": "ctrl+BackSpace",
        "description": "Delete one word to the left of the cursor",
    },
    "delete_word_right": {
        "keys": "ctrl+Delete",
        "description": "Delete one word to the right of the cursor",
    },
    "page_up": {
        "keys": "Prior",
        "description": "Scroll up one page",
    },
    "page_down": {
        "keys": "Next",
        "description": "Scroll down one page",
    },
}


# =============================================================================
# FREECAD SHORTCUTS (50 entries)
# Keys can be str (single keypress) or list[str] (sequential keypresses)
# =============================================================================

FREECAD_SHORTCUTS = {

    # ---- General (File / Edit) ----
    "file_new": {
        "keys": "ctrl+n",
        "description": "Create a new document",
    },
    "file_open": {
        "keys": "ctrl+o",
        "description": "Open an existing document",
    },
    "file_save": {
        "keys": "ctrl+s",
        "description": "Save the current document",
    },
    "file_save_as": {
        "keys": "ctrl+shift+s",
        "description": "Save the current document with a new name",
    },
    "file_import": {
        "keys": "ctrl+i",
        "description": "Import a file into the current document",
    },
    "file_export": {
        "keys": "ctrl+e",
        "description": "Export the current document or selection",
    },
    "file_print": {
        "keys": "ctrl+p",
        "description": "Print the current document",
    },
    "edit_undo": {
        "keys": "ctrl+z",
        "description": "Undo the last action",
    },
    "edit_redo": {
        "keys": "ctrl+y",
        "description": "Redo the last undone action",
    },
    "edit_copy": {
        "keys": "ctrl+c",
        "description": "Copy the selected object",
    },
    "edit_cut": {
        "keys": "ctrl+x",
        "description": "Cut the selected object",
    },
    "edit_paste": {
        "keys": "ctrl+v",
        "description": "Paste from clipboard",
    },
    "edit_delete": {
        "keys": "Delete",
        "description": "Delete the selected object",
    },
    "edit_refresh": {
        "keys": "F5",
        "description": "Refresh/recompute the document",
    },
    "edit_rename": {
        "keys": "F2",
        "description": "Rename the selected item in the tree",
    },
    "toggle_visibility": {
        "keys": "space",
        "description": "Toggle visibility of the selected object",
    },
    "cancel_operation": {
        "keys": "Escape",
        "description": "Cancel current operation / toggle navigation and edit mode",
    },
    "set_appearance": {
        "keys": "ctrl+d",
        "description": "Set appearance/display properties of selected object",
    },

    # ---- View Controls ----
    "view_isometric": {
        "keys": "0",
        "description": "Switch to isometric view",
    },
    "view_front": {
        "keys": "1",
        "description": "Switch to front view",
    },
    "view_top": {
        "keys": "2",
        "description": "Switch to top view",
    },
    "view_right": {
        "keys": "3",
        "description": "Switch to right view",
    },
    "view_rear": {
        "keys": "4",
        "description": "Switch to rear view",
    },
    "view_bottom": {
        "keys": "5",
        "description": "Switch to bottom view",
    },
    "view_left": {
        "keys": "6",
        "description": "Switch to left view",
    },
    "view_fit_all": {
        "keys": ["v", "f"],
        "description": "Fit entire model in the viewport (press V then F)",
    },
    "view_fit_selection": {
        "keys": ["v", "s"],
        "description": "Fit selected object in the viewport (press V then S)",
    },
    "view_orthographic": {
        "keys": ["v", "o"],
        "description": "Switch to orthographic projection (press V then O)",
    },
    "view_perspective": {
        "keys": ["v", "p"],
        "description": "Switch to perspective projection (press V then P)",
    },
    "view_drawstyle_wireframe": {
        "keys": ["v", "3"],
        "description": "Switch to wireframe draw style (press V then 3)",
    },
    "view_drawstyle_shaded": {
        "keys": ["v", "6"],
        "description": "Switch to shaded draw style (press V then 6)",
    },
    "view_drawstyle_flatlines": {
        "keys": ["v", "7"],
        "description": "Switch to flat lines (shaded + wireframe) draw style (press V then 7)",
    },
    "view_zoom_in": {
        "keys": "ctrl+plus",
        "description": "Zoom in on the viewport",
    },
    "view_zoom_out": {
        "keys": "ctrl+minus",
        "description": "Zoom out on the viewport",
    },
    "view_fullscreen": {
        "keys": "alt+F11",
        "description": "Toggle fullscreen mode",
    },

    # ---- Part Design ----
    # NOTE: Pad and Pocket have NO default keyboard shortcut in FreeCAD 1.0.
    # They must be accessed via the menu: Part Design → Pad / Pocket.
    # These entries are kept but DISABLED — do NOT add them to agent shortcut
    # filters or they will silently do nothing when called.
    # "partdesign_pad": {
    #     "keys": "p",
    #     "description": "Pad (extrude) the selected sketch into a solid",
    # },
    # "partdesign_pocket": {
    #     "keys": "q",
    #     "description": "Create a pocket (cut) from the selected sketch",
    # },

    # ---- Sketcher Geometry (G-prefix sequences) ----
    "sketcher_line": {
        "keys": ["g", "l"],
        "description": "Draw a line in the sketcher (press G then L)",
    },
    "sketcher_rectangle": {
        "keys": ["g", "r"],
        "description": "Draw a rectangle in the sketcher (press G then R)",
    },
    "sketcher_circle": {
        "keys": ["g", "c"],
        "description": "Draw a circle in the sketcher (press G then C)",
    },
    "sketcher_arc": {
        "keys": ["g", "a"],
        "description": "Draw an arc by center point in the sketcher (press G then A)",
    },
    "sketcher_polyline": {
        "keys": ["g", "m"],
        "description": "Draw a polyline in the sketcher (press G then M)",
    },
    "sketcher_point": {
        "keys": ["g", "y"],
        "description": "Create a point in the sketcher (press G then Y)",
    },
    "sketcher_slot": {
        "keys": ["g", "s"],
        "description": "Create a slot in the sketcher (press G then S)",
    },
    "sketcher_trim": {
        "keys": ["g", "t"],
        "description": "Trim an edge at intersection in the sketcher (press G then T)",
    },
    "sketcher_extend": {
        "keys": ["g", "q"],
        "description": "Extend an edge to the next intersection (press G then Q)",
    },
    "sketcher_external_geometry": {
        "keys": ["g", "x"],
        "description": "Reference external geometry in the sketcher (press G then X)",
    },
    "sketcher_construction_mode": {
        "keys": ["g", "n"],
        "description": "Toggle construction geometry mode (press G then N)",
    },

    # ---- Sketcher Constraints (single keys) ----
    "sketcher_constrain_horizontal": {
        "keys": "h",
        "description": "Constrain selected line or points to be horizontal",
    },
    "sketcher_constrain_vertical": {
        "keys": "v",
        "description": "Constrain selected line or points to be vertical",
    },
    "sketcher_constrain_coincident": {
        "keys": "c",
        "description": "Constrain two points to be coincident",
    },
    "sketcher_constrain_equal": {
        "keys": "e",
        "description": "Constrain two edges to have equal length or radius",
    },
    "sketcher_constrain_tangent": {
        "keys": "t",
        "description": "Constrain two edges to be tangent",
    },
    "sketcher_constrain_perpendicular": {
        "keys": "n",
        "description": "Constrain two lines to be perpendicular",
    },
    "sketcher_constrain_symmetric": {
        "keys": "s",
        "description": "Constrain two points to be symmetric about a line",
    },
    "sketcher_constrain_parallel": {
        "keys": "p",
        "description": "Constrain two lines to be parallel",
    },
    "sketcher_constrain_distance": {
        "keys": ["k", "d"],
        "description": "Set a distance constraint (press K then D)",
    },
    "sketcher_constrain_radius": {
        "keys": ["k", "r"],
        "description": "Set a radius constraint on a circle or arc (press K then R)",
    },
    "sketcher_constrain_angle": {
        "keys": ["k", "a"],
        "description": "Set an angle constraint between two lines (press K then A)",
    },
    "sketcher_constrain_lock": {
        "keys": ["k", "l"],
        "description": "Lock a point to a fixed position (press K then L)",
    },
    "sketcher_constrain_block": {
        "keys": ["k", "b"],
        "description": "Block an edge from moving (press K then B)",
    },
    "sketcher_constrain_horizontal_distance": {
        "keys": "l",
        "description": "Set a horizontal distance constraint",
    },
    "sketcher_constrain_vertical_distance": {
        "keys": "i",
        "description": "Set a vertical distance constraint",
    },
    "sketcher_constrain_point_on_object": {
        "keys": "o",
        "description": "Constrain a point onto an edge or line",
    },
    "sketcher_close": {
        "keys": "Escape",
        "description": "Close the sketch and return to Part Design",
    },

    # ---- Navigation / Display ----
    "toggle_axis_cross": {
        "keys": ["a", "c"],
        "description": "Toggle the axis cross display (press A then C)",
    },
    "next_document_tab": {
        "keys": "ctrl+Tab",
        "description": "Switch to the next document tab",
    },
    "prev_document_tab": {
        "keys": "ctrl+shift+Tab",
        "description": "Switch to the previous document tab",
    },

    # ---- Macro / Debug ----
    "macro_execute": {
        "keys": "ctrl+F6",
        "description": "Execute the current macro",
    },
    "macro_debug": {
        "keys": "F6",
        "description": "Start debugging the current macro",
    },
    "macro_toggle_breakpoint": {
        "keys": "F9",
        "description": "Toggle a breakpoint at the current line in macro editor",
    },

    # ---- Python Console ----
    "send_to_python_console": {
        "keys": "ctrl+shift+p",
        "description": "Send selected object to the Python console",
    },
}
