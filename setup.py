from setuptools import setup

APP = ["main.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "icon.icns",  # provide your own .icns file
    "plist": {
        "CFBundleName": "TextAssist",
        "CFBundleDisplayName": "TextAssist",
        "CFBundleIdentifier": "com.textassist.app",
        "CFBundleVersion": "1.0.0",
        "NSAccessibilityUsageDescription": (
            "TextAssist precisa de acesso de Acessibilidade para ler e "
            "substituir texto em outros aplicativos."
        ),
        "LSUIElement": True,  # hide from Dock; menu bar only
    },
    "packages": ["openai", "pynput", "rumps"],
    "includes": [
        "ApplicationServices",
        "AppKit",
        "Quartz",
    ],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
