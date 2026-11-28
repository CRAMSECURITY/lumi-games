import unittest
from types import SimpleNamespace
from lumi_media import MEDIA_LIMIT, media_size_allowed, BoundedMediaBuffer

class MediaTests(unittest.TestCase):
    def test_metadata(self):
        for size in (1, MEDIA_LIMIT, None):
            self.assertTrue(media_size_allowed(SimpleNamespace(file_size=size)))
        for size in (0,-1, MEDIA_LIMIT+1, True, '10'):
            self.assertFalse(media_size_allowed(SimpleNamespace(file_size=size)))
    def test_missing_metadata(self):
        self.assertTrue(media_size_allowed(SimpleNamespace()))
    def test_bounded_stream(self):
        with BoundedMediaBuffer() as stream:
            stream.write(b'a' * MEDIA_LIMIT)
            with self.assertRaises(ValueError):
                stream.write(b'b')
            self.assertEqual(len(stream.getvalue()), MEDIA_LIMIT)
    def test_repeated_chunks(self):
        with BoundedMediaBuffer() as stream:
            for _ in range(19):
                stream.write(b'a' * 1024 * 1024)
            with self.assertRaises(ValueError):
                stream.write(b'b')
