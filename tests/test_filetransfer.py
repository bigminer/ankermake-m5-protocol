import unittest
from queue import Empty
from types import SimpleNamespace

from libflagship.ppppapi import PPPPError
from web.service.filetransfer import FileTransferService


class FakeQueue:
    def __init__(self, result=None, fail=False):
        self.result = result
        self.fail = fail
        self.timeout = None

    def get(self, timeout=None):
        self.timeout = timeout
        if self.fail:
            raise Empty
        return self.result


class FileTransferTimeoutTests(unittest.TestCase):
    def test_acknowledgement_is_bounded(self):
        queue = FakeQueue(fail=True)
        service = SimpleNamespace(
            _tap=queue,
            api_aabb=lambda *args, **kwargs: None,
        )

        with self.assertRaisesRegex(ConnectionError, "offset 32768"):
            FileTransferService.api_aabb_request(
                service,
                api=object(),
                frametype=object(),
                msg=b"block",
                pos=32768,
            )

        self.assertEqual(queue.timeout, 15)

    def test_acknowledgement_returns_normally(self):
        response = SimpleNamespace(data=b"\x00")
        queue = FakeQueue(result=response)
        service = SimpleNamespace(
            _tap=queue,
            api_aabb=lambda *args, **kwargs: None,
            name="FileTransferService",
        )

        FileTransferService.api_aabb_request(
            service,
            api=object(),
            frametype=object(),
            msg=b"block",
            pos=0,
        )

        self.assertEqual(queue.timeout, 15)

    def test_nonzero_acknowledgement_is_rejected(self):
        queue = FakeQueue(result=SimpleNamespace(data=b"\xff"))
        service = SimpleNamespace(
            _tap=queue,
            api_aabb=lambda *args, **kwargs: None,
            name="FileTransferService",
        )

        with self.assertRaisesRegex(PPPPError, "ERR_BUSY"):
            FileTransferService.api_aabb_request(
                service,
                api=object(),
                frametype=object(),
                msg=b"block",
                pos=0,
            )

    def test_malformed_acknowledgement_is_rejected(self):
        queue = FakeQueue(result=SimpleNamespace(data=b""))
        service = SimpleNamespace(
            _tap=queue,
            api_aabb=lambda *args, **kwargs: None,
            name="FileTransferService",
        )

        with self.assertRaisesRegex(ValueError, "Unexpected file-transfer reply"):
            FileTransferService.api_aabb_request(
                service,
                api=object(),
                frametype=object(),
                msg=b"block",
                pos=0,
            )


if __name__ == "__main__":
    unittest.main()
