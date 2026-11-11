import asyncio
import json
import socket

from config import SERVICE_ID
from discovery import DiscoveryService, build_announcement, get_primary_ip, ip_for_peer


def test_announcement_payload():
    a = build_announcement("192.168.1.20", 8765, "PC")
    assert a["service"] == SERVICE_ID and a["type"] == "announce"
    assert a["host"] == "192.168.1.20" and a["port"] == 8765 and a["ws_path"] == "/ws"
    assert a["pin_required"] is True


def test_ip_helpers():
    assert ip_for_peer("127.0.0.1") == "127.0.0.1"
    assert get_primary_ip().count(".") == 3


async def test_probe_gets_reply(free_udp_port):
    svc = DiscoveryService(free_udp_port, server_port=8765, server_name="TEST-PC", interval=60)
    await svc.start()
    try:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.bind(("127.0.0.1", 0))
        probe = json.dumps({"service": SERVICE_ID, "type": "probe"}).encode()
        sock.sendto(probe, ("127.0.0.1", free_udp_port))
        data = await asyncio.wait_for(loop.sock_recv(sock, 4096), 3)
        reply = json.loads(data)
        assert reply["type"] == "probe_reply"
        assert reply["name"] == "TEST-PC" and reply["port"] == 8765 and reply["host"] == "127.0.0.1"
        assert svc.probes_answered == 1
        sock.close()
    finally:
        await svc.stop()


async def test_ignores_garbage_and_foreign_services(free_udp_port):
    svc = DiscoveryService(free_udp_port, server_port=8765, server_name="X", interval=60)
    await svc.start()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(b"not json", ("127.0.0.1", free_udp_port))
        s.sendto(json.dumps({"service": "other", "type": "probe"}).encode(), ("127.0.0.1", free_udp_port))
        await asyncio.sleep(0.3)
        assert svc.probes_answered == 0
        s.close()
    finally:
        await svc.stop()


async def test_announce_loop_runs(free_udp_port):
    svc = DiscoveryService(free_udp_port, server_port=8765, server_name="X", interval=0.1)
    await svc.start()
    await asyncio.sleep(0.35)
    await svc.stop()
    assert svc.announcements_sent >= 2
