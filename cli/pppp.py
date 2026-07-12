import os
import json
import time
import uuid
import logging as log
import ifaddr

from datetime import datetime, timedelta
from tqdm import tqdm

import cli.util

from libflagship.pktdump import PacketWriter
from libflagship.pppp import Duid, P2PCmdType, FileTransfer, PktLanSearch, PktPunchPkt, Xzyh, Aabb
from libflagship.ppppapi import AnkerPPPPApi, PPPPState


def _pppp_dumpfile(api, dumpfile):
    if dumpfile:
        log.info(f"Logging all pppp traffic to {dumpfile!r}")
        pktwr = PacketWriter.open(dumpfile)
        api.set_dumper(pktwr)


def pppp_open(config, printer_index, timeout=None, dumpfile=None):
    if timeout:
        deadline = datetime.now() + timedelta(seconds=timeout)

    with config.open() as cfg:
        if printer_index >= len(cfg.printers):
            log.critical(f"Printer number {printer_index} out of range, max printer number is {len(cfg.printers)-1} ")
        printer = cfg.printers[printer_index]

        if not printer.ip_addr:
            log.critical(f"Printer IP address not available")

        api = AnkerPPPPApi.open_lan(Duid.from_string(printer.p2p_duid), host=printer.ip_addr)
        _pppp_dumpfile(api, dumpfile)

        log.info(f"Trying connect to printer {printer.name} ({printer.p2p_duid}) over pppp using ip {printer.ip_addr}")

        api.connect_lan_search()
        api.start()

        while api.state != PPPPState.Connected:
            time.sleep(0.1)
            if api.stopped.is_set() or (timeout and (datetime.now() > deadline)):
                api.stop()
                raise ConnectionRefusedError("Connection rejected by device")

        log.info("Established pppp connection")
        return api


def pppp_open_broadcast(bind_addr=None, dumpfile=None):
    api = AnkerPPPPApi.open_broadcast(bind_addr=bind_addr)
    api.state = PPPPState.Connected
    _pppp_dumpfile(api, dumpfile)
    return api


def _pppp_get_interface_ip_addresses():
    adapters = ifaddr.get_adapters()
    for adapter in adapters:
        for ip in adapter.ips:
            # just consider IPv4 addresses (but exclude loopback)
            if isinstance(ip.ip, str) and not ip.ip.startswith("127."):
                yield ip.ip


def _pppp_query_printers(bind_addr=None, dumpfile=None):
    try:
        api = pppp_open_broadcast(bind_addr=bind_addr, dumpfile=dumpfile)
    except OSError:
        if bind_addr is not None:
            # accept binding errors and skip this address
            return
        raise

    api.send(PktLanSearch())

    # collect replies from all available printers within 1.0 second
    wait_time = 1.0
    timeout = time.monotonic() + wait_time
    while wait_time > 0:
        try:
            resp = api.recv(timeout=wait_time)
        except TimeoutError:
            pass
        else:
            if isinstance(resp, PktPunchPkt):
                yield str(resp.duid), api.addr[0]
        wait_time = timeout - time.monotonic()


def pppp_find_printer_ip_addresses(dumpfile=None):
    result = dict()
    if os.name == "nt":
        # Windows: We need to bind to each interface address
        for ip in _pppp_get_interface_ip_addresses():
            log.debug(f"Checking on interface with IP address {ip}")
            yield from _pppp_query_printers(bind_addr=ip, dumpfile=dumpfile)
    else:
        # Non-Windows: Broadcast goes out on all interfaces
        yield from _pppp_query_printers(dumpfile=dumpfile)


def _pppp_print_xzyh(chan, xzyh):
    try:
        cmd = P2PCmdType(xzyh.cmd).name
    except ValueError:
        cmd = f"0x{xzyh.cmd:04x}"

    try:
        body = json.dumps(json.loads(xzyh.data.decode()))
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = xzyh.data[:256].hex()

    log.info(f"chan{chan} XZYH cmd={cmd} len={xzyh.len} data={body}")


def pppp_listen(api, duration):
    """
    Print all channel traffic received within `duration` seconds.

    Protocol research helper: decodes XZYH and AABB frames arriving on any
    channel, and dumps anything unrecognized as hex. Returns the number of
    frames received.
    """
    deadline = time.monotonic() + duration
    frames = 0

    while time.monotonic() < deadline:
        for ch in api.chans:
            with ch.lock:
                hdr = ch.peek(16, timeout=0)
                if not hdr:
                    continue

                if hdr[:4] == b"XZYH":
                    xzyh = Xzyh.parse(hdr)[0]
                    data = ch.read(xzyh.len + 16, timeout=1.0)
                    if data is None:
                        continue
                    xzyh.data = data[16:]
                    frames += 1
                    _pppp_print_xzyh(ch.index, xzyh)
                elif hdr[:2] == b"\xaa\xbb":
                    hdr = ch.read(12, timeout=0)
                    aabb = Aabb.parse(hdr)[0]
                    body = (ch.read(aabb.len + 2, timeout=1.0) or b"")[:-2]
                    frames += 1
                    log.info(f"chan{ch.index} AABB frametype={aabb.frametype} sn={aabb.sn} data={body.hex()}")
                else:
                    junk = ch.read(16, timeout=0)
                    frames += 1
                    log.info(f"chan{ch.index} unknown data: {junk.hex()}")
        time.sleep(0.05)

    return frames


def pppp_send_file(api, fui, data):
    log.info("Requesting file transfer..")
    api.send_xzyh(str(uuid.uuid4())[:16].encode(), cmd=P2PCmdType.P2P_SEND_FILE)

    log.info("Sending file metadata..")
    api.aabb_request(bytes(fui), frametype=FileTransfer.BEGIN)

    log.info("Sending file contents..")
    blocksize = 1024 * 32

    with tqdm(unit="b", total=len(data), unit_scale=True, unit_divisor=1024) as bar:
        for pos, chunk in cli.util.split_chunks(data, blocksize):
            api.aabb_request(chunk, frametype=FileTransfer.DATA, pos=pos)
            bar.update(len(chunk))
