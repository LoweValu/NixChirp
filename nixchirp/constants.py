"""Default constants and configuration values."""

# Window defaults
DEFAULT_WINDOW_TITLE = "NixChirp"
DEFAULT_WINDOW_WIDTH = 960
DEFAULT_WINDOW_HEIGHT = 960

# Rendering
DEFAULT_FPS_CAP = 30
DEFAULT_BG_COLOR = (0.0, 0.0, 0.0, 0.0)  # Transparent
CHROMA_GREEN = (0.0, 1.0, 0.0, 1.0)       # #00FF00

# Frame cache
DEFAULT_CACHE_MAX_MB = 512

# Animation
DEFAULT_SPEED_MULTIPLIER = 1.0
MIN_SPEED_MULTIPLIER = 0.1
MAX_SPEED_MULTIPLIER = 5.0

# Mic defaults
DEFAULT_MIC_OPEN_THRESHOLD = 0.08
DEFAULT_MIC_CLOSE_THRESHOLD = 0.05
DEFAULT_MIC_HOLD_TIME_MS = 150

# Sleep (deep idle / screensaver)
DEFAULT_SLEEP_TIMEOUT_SECONDS = 30

# Output modes
OUTPUT_TRANSPARENT = "transparent"
OUTPUT_CHROMA = "chroma"
OUTPUT_VIRTUAL_CAM = "virtual_cam"
OUTPUT_WINDOWED = "windowed"
