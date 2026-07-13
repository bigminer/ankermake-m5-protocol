import click
import logging as log

import cli.util

from libflagship import ROOT_DIR
from libflagship.transport import MqttTransport

servertable = {
    "eu": "make-mqtt-eu.ankermake.com",
    "us": "make-mqtt.ankermake.com",
}


def mqtt_transport(config, printer_index, insecure):
    """Build an unconnected MqttTransport for the given printer from config."""
    with config.open() as cfg:
        if printer_index >= len(cfg.printers):
            log.critical(f"Printer number {printer_index} out of range, max printer number is {len(cfg.printers)-1} ")
            raise IndexError(f"Printer number {printer_index} out of range")
        printer = cfg.printers[printer_index]
        acct = cfg.account
        server = servertable[acct.region]
        log.info(f"Connecting printer {printer.name} ({printer.p2p_duid}) through {server}")
        return MqttTransport(
            printersn=printer.sn,
            username=acct.mqtt_username,
            password=acct.mqtt_password,
            key=printer.mqtt_key,
            server=server,
            ca_certs=ROOT_DIR / "ssl/ankermake-mqtt.crt",
            verify=not insecure,
        )


def mqtt_open(config, printer_index, insecure):
    """Connect to the printer and return the underlying MQTT client (CLI API)."""
    transport = mqtt_transport(config, printer_index, insecure)
    transport.connect()
    return transport.client


def mqtt_command(client, msg):
    client.command(msg)

    reply = client.await_response(msg["commandType"])
    if reply:
        click.echo(cli.util.pretty_json(reply))
    else:
        log.error("No response from printer")


def mqtt_query(client, msg):
    client.query(msg)

    reply = client.await_response(msg["commandType"])
    if reply:
        click.echo(cli.util.pretty_json(reply))
    else:
        log.error("No response from printer")
