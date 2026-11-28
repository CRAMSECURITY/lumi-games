"""Exact Telegram media identity checks; no downloads or biometric matching."""
def media_identity(media):
    value = getattr(media, 'file_unique_id', None)
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


def init_media_identity(db):
    if 'media_unique_id' not in {r[1] for r in db.execute('PRAGMA table_info(profiles)')}:
        db.execute('ALTER TABLE profiles ADD COLUMN media_unique_id TEXT')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS profiles_media_unique ON profiles(media_unique_id) WHERE media_unique_id IS NOT NULL')


def media_available(db, user_id, identity, photo_id, video_id):
    # Caller holds BEGIN IMMEDIATE until the profile write commits.
    return db.execute('''SELECT 1 FROM profiles WHERE user_id<>? AND
        ((? IS NOT NULL AND media_unique_id=?) OR
         (? IS NOT NULL AND photo_id=?) OR (? IS NOT NULL AND video_id=?)) LIMIT 1''',
        (user_id, identity, identity, photo_id, photo_id, video_id, video_id)).fetchone() is None
