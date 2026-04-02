# TextAssist
**TextAssist** is an out-of-process macOS application that brings advanced grammar, style, and spelling suggestions globally to any native text input (TextEdit, Notes, Mail). It tracks the text cursor and dynamically overlays spelling (red) and grammar/style (yellow) suggestions over native input fields using the native macOS Accessibility API.

## Features
- **Global Check:** Corrects text system-wide without plugins.
- **Native Out-of-Process Rendering:** Draws native `NSPanel` UI floating directly over your typing, adopting a sleek frosted glass material design.
- **Hide-on-Change Engine:** Seamlessly tracks your scrolling, window bounds, and popups. Hide-on-Change tracking ensures the overlays disappear predictably when menus shift and snap back naturally to keep text readable.
- **Advanced Grammar AI:** Uses OpenAI to evaluate complex phrasings, style weaknesses, and punctuation alongside strict spelling constraints.
- **Correction UI:** Click on any highlighted word or sentence to spawn a native inline Fix-Card. Includes interactive diff previews, add-to-dictionary controls, and batch "Fix All" application routines.

## Installation
### Requirements
- macOS (requires Accessibility Permissions).
- Python 3.10+ (pyobjc bindings).
- OpenAI API Key.

### Setup
```bash
# 1. Clone the repository
git clone https://github.com/dronan/gramar-check.git
cd gramar-check

# 2. Duplicate the environment variables and fill with your OpenAI Key
cp .env.example config.py
# (Edit config.py to contain: OPENAI_API_KEY = "sk-...")

# 3. Install requirements
pip install -r requirements.txt
```

## Usage
Start the background daemon process:
```bash
python3 main.py
```
The first time you run the application, macOS will prompt you to grant Accessibility permissions to your Terminal or Python executable.
After granting permissions, open a native app like TextEdit, type an incorrect sentence (e.g. `I'll write this phrase incorectly`), wait ~2 seconds, and the correction interface will automatically appear overlaid on top of your text.

## Technical Details
* **Accessibility Wrappers (`ax_monitor.py`):** Uses pure C-level `ctypes` wrappers around Quartz and CoreFoundation ApplicationServices APIs to successfully evaluate `AXBoundsForRange` bypassing some opaque pyobjc limitations.
* **PID Trapping (`watcher.py`):** Deep integration verifies the `AXUIElementGetPid` system calls to trap and bypass UI closure bugs when user focus shifts into the non-activating TextAssist correction card window.
* **Smart UI Layout (`correction_card.py` & `overlay.py`):** Mathematical segmentation natively extracts and bridges individual bounded boxes so grammar lines wrap automatically when reaching the limits of text areas.
