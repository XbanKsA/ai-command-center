"""
UDP auto-discovery so the tablet never needs a manual IP.

Two complementary mechanisms on the same UDP port (default 37020):

  1. ANNOUNCE (passive): every BROADCAST_INTERVAL seconds the PC broadcasts
       {"service": "ai-command-center", "type": "announce", "host": "<pc ip>", "port": 8765, ...}
     to every network interface's broadcast address + 255.255.255.255.

  2. PROBE (active): a client broadcasts {"service": "ai-command-center", "type": "probe"}
     to port 37020; the PC answers it directly (unicast) with the same announce payload.
     This is faster and works even when the client can't bind port 37020 itself.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket

import psutil

from config import SERVICE_ID, VERSION

log = logging.getLogger("discovery")


def get_primary_ip() -> str:
    """The LAN IP Windows would use to reach the internet/router (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ip_for_peer(peer_ip: str) -> str:
    """Pick the local IP on the same network as `peer_ip` (so the reply contains a reachable address)."""
    if peer_ip.startswith("127."):
        return "127.0.0.1"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((peer_ip, 9))
        return s.getsockname()[0]
    except OSError:
        return get_primary_ip()
    finally:
        s.close()


def get_broadcast_targets() -> list[tuple[str, str]]:
    """[(local_ip, broadcast_addr), ...] for every active IPv4 interface (skips loopback / link-local)."""
    targets: list[tuple[str, str]] = []
    try:
        stats = psutil.net_if_stats()
        for ifname, addrs in psutil.net_if_addrs().items():
            if ifname in stats and not stats[ifname].isup:
                continue
            for a in addrs:
                if a.family != socket.AF_INET or not a.address or not a.netmask:
                    continue
                ip = ipaddress.IPv4Address(a.address)
                if ip.is_loopback or ip.is_link_local:
                    continue
                net = ipaddress.IPv4Network(f"{a.address}/{a.netmask}", strict=False)
                targets.append((a.address, str(net.broadcast_address)))
    except Exception as exc:
        log.debug("interface enumeration failed: %s", exc)
    return targets


def get_lan_ips() -> list[str]:
    return sorted({ip for ip, _ in get_broadcast_targets()}) or [get_primary_ip()]


def build_announcement(host_ip: str, server_port: int, server_name: str) -> dict:
    return {
        "service": SERVICE_ID,
        "type": "announce",
        "version": VERSION,
        "name": server_name,
        "host": host_ip,
        "port": server_port,
        "ws_path": "/ws",
        "pin_required": True,
    }


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, service: "DiscoveryService"):
        self.service = service
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(msg, dict) or msg.get("service") != SERVICE_ID:
            return
        if msg.get("type") != "probe":
            return  # ignore our own announcements & other traffic
        peer_ip, peer_port = addr[0], addr[1]
        reply = build_announcement(ip_for_peer(peer_ip), self.service.server_port, self.service.server_name)
        reply["type"] = "probe_reply"
        self.service.probes_answered += 1
        log.debug("Discovery probe from %s:%s -> replied with %s", peer_ip, peer_port, reply["host"])
        if self.transport:
            self.transport.sendto(json.dumps(reply).encode("utf-8"), (peer_ip, peer_port))

    def error_received(self, exc):
        log.debug("UDP error: %s", exc)


class DiscoveryService:
    def __init__(self, discovery_port: int, server_port: int, server_name: str, interval: float = 2.0):
        self.discovery_port = discovery_port
        self.server_port = server_port
        self.server_name = server_name
        self.interval = interval
        self.probes_answered = 0
        self.announcements_sent = 0
        self._transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task | None = None

    def _make_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", self.discovery_port))
        sock.setblocking(False)
        return sock

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self), sock=self._make_socket())
        self._task = asyncio.create_task(self._announce_loop())
        log.info("Discovery listening/broadcasting on UDP %d", self.discovery_port)

    async def _announce_loop(self) -> None:
        while True:
            try:
                self.announce_once()
            except Exception as exc:
                log.debug("announce failed: %s", exc)
            await asyncio.sleep(self.interval)

    def announce_once(self) -> None:
        if not self._transport:
            return
        targets = get_broadcast_targets()
        for local_ip, bcast in targets:
            payload = json.dumps(build_announcement(local_ip, self.server_port, self.server_name)).encode()
            try:
                self._transport.sendto(payload, (bcast, self.discovery_port))
            except OSError:
                pass
        # Global broadcast too (some Wi-Fi drivers only forward this one)
        payload = json.dumps(build_announcement(get_primary_ip(), self.server_port, self.server_name)).encode()
        try:
            self._transport.sendto(payload, ("255.255.255.255", self.discovery_port))
        except OSError:
            pass
        self.announcements_sent += 1

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._transport:
            self._transport.close()
