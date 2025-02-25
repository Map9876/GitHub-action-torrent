import asyncio
import websockets
import json
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer
from download_torrent import TorrentDownloader, start_download

# HTTP server to serve the web UI
class CustomHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        return super().end_headers()

def start_http_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, CustomHandler)
    print("HTTP server running on http://localhost:8000")
    httpd.serve_forever()

# WebSocket server to handle real-time updates
async def websocket_handler(websocket, path):
    async for message in websocket:
        await websocket.send(message)

def start_websocket_server():
    websocket_server = websockets.serve(websocket_handler, "localhost", 8765)
    return websocket_server

def start_cloudflared():
    process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for line in process.stdout:
        print(line.decode().strip())

async def main(magnet_link, save_path, huggingface_token):
    # Start the HTTP server
    asyncio.create_task(asyncio.to_thread(start_http_server))
    # Start the cloudflared tunnel
    asyncio.create_task(asyncio.to_thread(start_cloudflared))
    # Start the WebSocket server
    await start_websocket_server()
    # Start the torrent downloader
    await start_download(magnet_link, save_path, huggingface_token)

if __name__ == "__main__":
    magnet_link = "magnet:?xt=urn:btih:8123f386aa6a45e26161753a3c0778f8b9b4d4cb&dn=Totoro_FTR-4_F_EN-en-CCAP_US-G_51_2K_GKID_20230303_GKD_IOP_OV&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&tr=udp%3A%2F%2Fexodus.desync.com%3A6969%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce"
    save_path = "Torrent/"
    huggingface_token = sys.argv[1]
    asyncio.run(main(magnet_link, save_path, huggingface_token))