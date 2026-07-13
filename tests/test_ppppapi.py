import hashlib
import io
import unittest

from libflagship.ppppapi import Channel, FileUploadInfo


class ChannelWriteTimeoutTests(unittest.TestCase):
    def test_blocking_write_times_out_without_acks(self):
        chan = Channel(1)

        with self.assertRaisesRegex(TimeoutError, "channel 1"):
            chan.write(b"payload", block=True, timeout=0.1)

    def test_blocking_write_returns_once_acked(self):
        chan = Channel(1)
        # pre-acknowledge the single 1kb chunk the write will schedule
        chan.rx_ack([0])

        start, done = chan.write(b"payload", block=True, timeout=1)

        self.assertEqual((int(start), int(done)), (0, 1))

    def test_non_blocking_write_returns_immediately(self):
        chan = Channel(1)

        start, done = chan.write(b"payload", block=False)

        self.assertEqual((int(start), int(done)), (0, 1))


class FileUploadInfoTests(unittest.TestCase):
    def test_from_stream_hashes_and_rewinds(self):
        data = b"chunked upload data"
        stream = io.BytesIO(data)

        info = FileUploadInfo.from_stream(
            stream, "test.gcode", user_name="test", user_id="-", machine_id="-",
            blocksize=4,
        )

        self.assertEqual(info.size, len(data))
        self.assertEqual(info.md5, hashlib.md5(data).hexdigest())
        self.assertEqual(stream.read(), data)

if __name__ == "__main__":
    unittest.main()
