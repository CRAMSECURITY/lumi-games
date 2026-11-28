"""Experimental local recommendation scoring; never selects eligibility."""
import re
import unicodedata


def tokens(value):
    value = unicodedata.normalize('NFKC', (value or '')[:4096]).casefold()
    stop = {"это", "хочу", "ищу", "люблю", "очень", "как", "мой", "моя", "себе", "свой", "все", "нет", "указано"}
    return {w for w in re.findall(r'[^\W_]+', value, flags=re.UNICODE)[:256] if len(w) >= 3 and w not in stop}


def city_key(value):
    return ' '.join(unicodedata.normalize('NFKC', (value or '')[:256]).casefold().split())


def score(my_city, my_interests, city, interests):
    """0–100 ranking score, not a probability or psychological assessment."""
    a, b = tokens(my_interests), tokens(interests)
    common = len(a & b)
    # Saturating overlap rewards shared interests without rewarding long profiles.
    overlap = 60 * common / len(a | b) if a and b else 0
    local = 40 if city_key(my_city) and city_key(my_city) == city_key(city) else 0
    return overlap + local
