"""Printer transport abstraction.

A `PrinterTransport` is the channel the app uses to exchange control commands
and telemetry with a printer. Today the only implementation is `MqttTransport`
(the Anker MQTT protocol, whether it terminates at Anker's cloud or a local
broker — the difference is only the `server` address). The interface exists so
other channels (e.g. a stock-Marlin serial bridge) can slot in behind the same
contract, and so the app can be driven by a fake in tests without any cloud
account.

File uploads ride PPPP separately and are intentionally not part of this
interface.
"""

from abc import ABC, abstractmethod

from libflagship.mqttapi import AnkerMQTTBaseClient


class PrinterTransport(ABC):

    @abstractmethod
    def connect(self):
        """Establish the channel. Must be called before command/query/fetch."""

    @abstractmethod
    def disconnect(self):
        """Tear down the channel. Safe to call if never connected."""

    @abstractmethod
    def fetch(self, timeout=1.0):
        """Return a list of (msg, body) telemetry tuples seen within `timeout`."""

    @abstractmethod
    def command(self, msg):
        """Send a control command (a decoded command dict)."""

    @abstractmethod
    def query(self, msg):
        """Send a status query (a decoded query dict)."""


class MqttTransport(PrinterTransport):
    """PrinterTransport over the Anker MQTT protocol.

    `client_factory` builds the underlying `AnkerMQTTBaseClient`; it is injectable
    so tests can supply a fake without touching the network.
    """

    def __init__(self, *, printersn, username, password, key, server, port=8789,
                 ca_certs=None, verify=True, client_factory=AnkerMQTTBaseClient.login):
        self._printersn = printersn
        self._username = username
        self._password = password
        self._key = key
        self._server = server
        self._port = port
        self._ca_certs = ca_certs
        self._verify = verify
        self._client_factory = client_factory
        self._client = None

    @property
    def client(self):
        """The underlying AnkerMQTTBaseClient (for CLI callers needing its full
        API, e.g. await_response). None until connect()."""
        return self._client

    def connect(self):
        self._client = self._client_factory(
            self._printersn, self._username, self._password, self._key,
            ca_certs=self._ca_certs, verify=self._verify,
        )
        self._client.connect(self._server, self._port)

    def disconnect(self):
        if self._client is not None:
            self._client.disconnect()

    def fetch(self, timeout=1.0):
        return self._client.fetch(timeout=timeout)

    def command(self, msg):
        return self._client.command(msg)

    def query(self, msg):
        return self._client.query(msg)
