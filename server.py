import asyncio
import websockets
import json
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer
from download_torrent import TorrentDownloader, start_download
import threading

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

async def websocket_handler(websocket, path):
    async for message in websocket:
        await websocket.send(message)

def start_websocket_server():
    websocket_server = websockets.serve(websocket_handler, "localhost", 8765)
    return websocket_server

def read_output(pipe, prefix):
    """Helper function to read and print output from subprocess pipes"""
    try:
        for line in iter(pipe.readline, ''):
            if line:  # 确保行不为空
                # 如果输入已经是字符串，直接使用；如果是字节，则解码
                line_str = line if isinstance(line, str) else line.decode()
                print(f"{prefix}: {line_str.strip()}")
    except Exception as e:
        print(f"Error in read_output: {str(e)}")

def start_cloudflared():
    try:
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True  # 这会自动处理文本流而不是字节流
        )
        
        stdout_thread = threading.Thread(target=read_output, args=(process.stdout, "CLOUDFLARED STDOUT"))
        stderr_thread = threading.Thread(target=read_output, args=(process.stderr, "CLOUDFLARED STDERR"))
        
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        
        process.wait()
    except Exception as e:
        print(f"Error starting cloudflared: {str(e)}")

async def main(magnet_link, save_path, huggingface_token):
    http_server_thread = threading.Thread(target=start_http_server)
    http_server_thread.daemon = True
    http_server_thread.start()

    cloudflared_thread = threading.Thread(target=start_cloudflared)
    cloudflared_thread.daemon = True
    cloudflared_thread.start()

    await start_websocket_server()
    await start_download(magnet_link, save_path, huggingface_token)

if __name__ == "__main__":
    magnet_link = "magnet:?xt=urn:btih:8123f386aa6a45e26161753a3c0778f8b9b4d4cb&dn=Totoro_FTR-4_F_EN-en-CCAP_US-G_51_2K_GKID_20230303_GKD_IOP_OV&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&tr=udp%3A%2F%2Fexodus.desync.com%3A6969%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce"
    save_path = "Torrent/"
    huggingface_token = sys.argv[1]
    asyncio.run(main(magnet_link, save_path, huggingface_token))