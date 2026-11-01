"""shapeyourphone: let an AI agent reshape an Android phone, reversibly, over ADB."""

__version__ = "0.1.0"

# The launcher app this toolkit installs and controls.
LAUNCHER_PACKAGE = "io.github.rachitkj.shape"
LAUNCHER_AUTHORITY = LAUNCHER_PACKAGE + ".control"
LAUNCHER_HOME_ACTIVITY = LAUNCHER_PACKAGE + "/.HomeActivity"
LAUNCHER_RELEASE_URL = (
    "https://github.com/rachitkj/shapeyourphone/releases/latest/download/shape-launcher.apk"
)
