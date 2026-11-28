"""Local, advisory link and scam indicators; never logs message content."""
import re
import unicodedata

LINK = re.compile(r'(?:https?\s*[:：]|www\.|(?:[\w-]+\.)+(?:com|net|org|ru|рф|io|me|app|xyz|top|site|click|online|info|dev|ly)\b)', re.I)
RISK = re.compile(r'\b(?:код\s+(?:из\s+)?(?:смс|sms|телеграм|telegram|подтверждения)|seed\s+phrase|private\s+key|verification\s+code|предоплат\w*|гарантированн\w*\s+(?:доход|прибыл\w*)|переведи\s+деньги)\b', re.I)
WARNING = '\n\n🛡 LUMI: будьте осторожны со ссылками и просьбами о деньгах или кодах. Не передавайте данные входа. При подозрении используйте блокировку или жалобу.'


def warning_for(text, entities=()):
    normalized = unicodedata.normalize('NFKC', text or '')
    normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Cf')
    has_link = any(getattr(e, 'type', None) in ('url', 'text_link') for e in (entities or ()))
    return WARNING if has_link or LINK.search(normalized) or RISK.search(normalized) else ''
