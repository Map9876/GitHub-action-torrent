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
import time
import aiohttp


class HealthCheckHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthz':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
        else:
            super().do_GET()

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        return super().end_headers()

async def check_http_server():
    """检查HTTP服务是否就绪"""
    async with aiohttp.ClientSession() as session:
        for _ in range(30):  # 最多重试30次
            try:
                async with session.get('http://localhost:8000/healthz') as resp:
                    if resp.status == 200:
                        return True
            except:
                pass
            await asyncio.sleep(1)
        return False

def start_http_server():
    """启动HTTP服务器"""
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print("HTTP server running on http://localhost:8000")
    httpd.serve_forever()

async def monitor_cloudflared(process):
    """监控cloudflared进程并提取URL"""
    url = None
    while True:
        line = process.stdout.readline()
        if not line:
            break
        
        line_str = line if isinstance(line, str) else line.decode()
        
        # 提取cloudflare公共URL
        if 'trycloudflare.com' in line_str.lower():
            url = line_str.strip()
            print("\n" + "="*50)
            print("CLOUDFLARED PUBLIC URL:")
            print(url)
            print("="*50 + "\n")
            break
        
        print(f"CLOUDFLARED: {line_str.strip()}")
    
    return url

async def start_cloudflared():
    """启动并监控cloudflared"""
    print("\nStarting cloudflared tunnel...")
    try:
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True
        )
        
        # 等待获取公共URL
        url = await monitor_cloudflared(process)
        if not url:
            raise RuntimeError("Failed to get cloudflared URL")
        
        return process, url
    except Exception as e:
        print(f"Error starting cloudflared: {str(e)}")
        return None, None

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
    # 启动HTTP服务器
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # 等待HTTP服务器启动
    if not await check_http_server():
        raise RuntimeError("HTTP server failed to start")
    
    # 启动cloudflared
    cloudflared_process, cloudflared_url = await start_cloudflared()
    if not cloudflared_process:
        raise RuntimeError("Failed to start cloudflared")

    # 启动WebSocket服务器
    websocket_task = asyncio.create_task(start_websocket_server())

    # 启动下载任务
    download_task = asyncio.create_task(
        start_download(magnet_link, save_path, huggingface_token))
    
    # 等待所有任务完成
    await asyncio.gather(
        websocket_task,
        download_task
    )

if __name__ == "__main__":
    magnet_link = "magnet:?xt=urn:btih:UPDH7IQHVPOHYBBJQYFSTUEEI6G2AD6K&dn=&tr=http%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=udp%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=http%3A%2F%2Ftracker.openbittorrent.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=http%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftracker.publicbt.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker.prq.to%2Fannounce&tr=http%3A%2F%2Fopen.acgtracker.com%3A1096%2Fannounce&tr=https%3A%2F%2Ft-115.rhcloud.com%2Fonly_for_ylbud&tr=http%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=http%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=udp%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftr.bangumi.moe%3A6969%2Fannounce"
    save_path = "Torrent/"
    huggingface_token = sys.argv[1]
    
    print(f'Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f"Current User's Login: map9876543")
    
    try:
        asyncio.run(main(magnet_link, save_path, huggingface_token))
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)