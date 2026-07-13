import unittest

from libflagship.transport import PrinterTransport, MqttTransport


class _FakeClient:
    """Stand-in for AnkerMQTTBaseClient recording the calls a transport makes."""

    def __init__(self, printersn, username, password, key, ca_certs=None, verify=True):
        self.init_args = dict(printersn=printersn, username=username, password=password,
                              key=key, ca_certs=ca_certs, verify=verify)
        self.connected_to = None
        self.disconnected = False
        self.commands = []
        self.queries = []
        self.fetch_result = [("msg", ["body"])]

    def connect(self, server, port):
        self.connected_to = (server, port)

    def disconnect(self):
        self.disconnected = True

    def fetch(self, timeout=1.0):
        return self.fetch_result

    def command(self, msg):
        self.commands.append(msg)

    def query(self, msg):
        self.queries.append(msg)


def _make_transport(**overrides):
    created = {}

    def factory(printersn, username, password, key, ca_certs=None, verify=True):
        client = _FakeClient(printersn, username, password, key, ca_certs, verify)
        created["client"] = client
        return client

    params = dict(printersn="SN123", username="user", password="pw", key=b"k",
                  server="broker.local", port=8789, verify=False, client_factory=factory)
    params.update(overrides)
    return MqttTransport(**params), created


class MqttTransportTests(unittest.TestCase):

    def test_is_a_printer_transport(self):
        transport, _ = _make_transport()
        self.assertIsInstance(transport, PrinterTransport)

    def test_client_is_none_before_connect(self):
        transport, _ = _make_transport()
        self.assertIsNone(transport.client)

    def test_connect_builds_client_with_creds_and_dials_server(self):
        transport, created = _make_transport()
        transport.connect()
        client = created["client"]
        self.assertIs(transport.client, client)
        self.assertEqual(client.init_args["printersn"], "SN123")
        self.assertEqual(client.init_args["verify"], False)
        self.assertEqual(client.connected_to, ("broker.local", 8789))

    def test_command_query_fetch_delegate_to_client(self):
        transport, created = _make_transport()
        transport.connect()
        client = created["client"]
        transport.command({"commandType": 1})
        transport.query({"commandType": 2})
        result = transport.fetch(timeout=0.5)
        self.assertEqual(client.commands, [{"commandType": 1}])
        self.assertEqual(client.queries, [{"commandType": 2}])
        self.assertEqual(result, [("msg", ["body"])])

    def test_disconnect_before_connect_is_safe(self):
        transport, _ = _make_transport()
        transport.disconnect()  # must not raise

    def test_disconnect_delegates_after_connect(self):
        transport, created = _make_transport()
        transport.connect()
        transport.disconnect()
        self.assertTrue(created["client"].disconnected)


class FakeTransportTests(unittest.TestCase):
    """A non-MQTT PrinterTransport can be implemented and driven without any
    cloud account — the point of the abstraction."""

    def test_fake_transport_satisfies_interface(self):
        class FakeTransport(PrinterTransport):
            def __init__(self):
                self.sent = []
                self.events = [("m", ["telemetry"])]

            def connect(self):
                pass

            def disconnect(self):
                pass

            def fetch(self, timeout=1.0):
                return self.events

            def command(self, msg):
                self.sent.append(("command", msg))

            def query(self, msg):
                self.sent.append(("query", msg))

        t = FakeTransport()
        t.connect()
        t.command({"commandType": 9})
        self.assertEqual(t.fetch(), [("m", ["telemetry"])])
        self.assertEqual(t.sent, [("command", {"commandType": 9})])


if __name__ == "__main__":
    unittest.main()
