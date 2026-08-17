"""Local TCP reverse proxy: 127.0.0.1:18791 -> classroom hub (Tailscale LAN)."""
import asyncio
import os

UPSTREAM_HOST = os.environ.get("DFTB_HUB_UPSTREAM_HOST", "100.127.118.69")
UPSTREAM_PORT = int(os.environ.get("DFTB_HUB_UPSTREAM_PORT", "8791"))
LISTEN_HOST = os.environ.get("DFTB_HUB_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("DFTB_HUB_PROXY_PORT", "18791"))

async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def handle(local_reader, local_writer):
    try:
        remote_reader, remote_writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
    except Exception as e:
        local_writer.close()
        print("upstream fail", e, flush=True)
        return
    await asyncio.gather(
        pipe(local_reader, remote_writer),
        pipe(remote_reader, local_writer),
    )

async def main():
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    print(f"proxy {LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM_HOST}:{UPSTREAM_PORT}", flush=True)
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
