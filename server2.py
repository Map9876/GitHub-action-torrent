import asyncio
import websockets
import json
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer

from k import start_download
import threading
from datetime import datetime
from dler import download_manager

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

def read_output(pipe, prefix):

    """读取并打印输出流"""
    while True:
        try:
            line = pipe.readline()
            if not line:
                break
            
            line_str = line if isinstance(line, str) else line.decode()
            
            # 特别关注 cloudflared 链接
            if any(x in line_str.lower() for x in ['trycloudflare.com', 'cloudflare.com']):
                print("\n" + "="*50)
                print("CLOUDFLARED PUBLIC URL:")
                print(line_str.strip())
                print("="*50 + "\n")
            
            # 始终打印输出
            print(f"{prefix}: {line_str.strip()}")
            sys.stdout.flush()  # 确保立即输出
            
        except Exception as e:
            print(f"Error reading output: {e}")
            break

def start_cloudflared():
    """启动 cloudflared 并实时显示输出"""
    print("\nStarting cloudflared tunnel...")

    try:
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True
        )
        

        # 创建并启动输出监控线程
        stdout_thread = threading.Thread(
            target=read_output, 
            args=(process.stdout, "CLOUDFLARED"),
            name="CloudflaredStdout"
        )
        stderr_thread = threading.Thread(
            target=read_output, 
            args=(process.stderr, "CLOUDFLARED ERR"),
            name="CloudflaredStderr"
        )
        
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        

        stdout_thread.start()
        stderr_thread.start()
        
        return process
    except Exception as e:
        print(f"Error starting cloudflared: {str(e)}")
        return None


async def websocket_handler(websocket, path):
    await download_manager.register(websocket)
    try:
        async for message in websocket:
            # Handle any client messages if needed
            pass
    finally:
        await download_manager.unregister(websocket)

async def start_websocket_server():
    async with websockets.serve(websocket_handler, "localhost", 8765):
        await asyncio.Future()  # run forever

async def main(magnet_link, save_path, huggingface_token):
    # Start the HTTP server
    http_thread = threading.Thread(target=start_http_server)
    http_thread.daemon = True
    http_thread.start()

    # Start cloudflared
    cloudflared_process = start_cloudflared()

    # Start the WebSocket server
    websocket_task = asyncio.create_task(start_websocket_server())


    # Start the torrent downloader
    await start_download(magnet_link, save_path, huggingface_token)


if __name__ == "__main__":
    magnet_link = "your_magnet_link_here"
    save_path = "Torrent/"
    huggingface_token = sys.argv[1]

    print(f'Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f"Current User's Login: map9876543")
    asyncio.run(main(magnet_link, save_path, huggingface_token))