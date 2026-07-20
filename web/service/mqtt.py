import logging as log

from ..lib.service import Service
from .. import app

from libflagship.util import enhex

import cli.mqtt


class MqttQueue(Service):

    def worker_start(self):
        self.transport = cli.mqtt.mqtt_transport(
            app.config["config"],
            app.config["printer_index"],
            app.config["insecure"]
        )
        self.transport.connect()

    def worker_run(self, timeout):
        for msg, body in self.transport.fetch(timeout=timeout):
            log.info(f"TOPIC [{msg.topic}]")
            log.debug(enhex(msg.payload[:]))

            for obj in body:
                from .state import normalize
                normalized = normalize(obj)
                if normalized:
                    printer_id = f"printer-{app.config['printer_index']}"
                    app.printer_snapshots.observe(printer_id, normalized)
                self.notify(obj)
        app.printer_snapshots.tick()
        if app.printer_actions is not None:
            app.printer_actions.tick()

    def worker_stop(self):
        try:
            self.transport.disconnect()
        except Exception as E:
            log.warning(f"{self.name}: Failed to disconnect mqtt transport ({E})")
        del self.transport
