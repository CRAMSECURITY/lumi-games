"""Local profile text validation; no external services or content logging."""
import unicodedata
from lumi_anti_scam import warning_for


def profile_text_allowed(text, entities=()):
    if not isinstance(text, str):
        return False
    # Reject directional overrides, invisible-only strings and control characters.
    if any(unicodedata.category(c) in ('Cc', 'Cs') and c not in '\n\t' or ord(c) in range(0x202a, 0x202f) or ord(c) in range(0x2066, 0x206a) for c in text):
        return False
    visible = ''.join(c for c in text if unicodedata.category(c) not in ('Cf', 'Mn', 'Me')).strip()
    return bool(visible) and not warning_for(text, entities)
