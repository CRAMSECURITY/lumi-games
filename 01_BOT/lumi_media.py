"""Bound media resource use; Telegram metadata is not content verification."""
from io import BytesIO

MEDIA_LIMIT = 19 * 1024 * 1024


def media_size_allowed(media):
    size = getattr(media, 'file_size', None)
    return size is None or (type(size) is int and 0 < size <= MEDIA_LIMIT)


class BoundedMediaBuffer(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MEDIA_LIMIT:
            raise ValueError('Медиа превышает лимит безопасной передачи')
        return super().write(data)
