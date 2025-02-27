import asyncio
import websockets
import json
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer
from k import start_download
import threading
from datetime import datetime, UTC
from dler import download_manager
import time
import aiohttp
import signal

class HealthCheckHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthz':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {'status': 'ok', 'timestamp': datetime.now(UTC).isoformat()}
            self.wfile.write(json.dumps(response).encode())
            # Add debug output
            print("Health check request handled successfully")
        else:
            super().do_GET()

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        return super().end_headers()

    def log_message(self, format, *args):
        # Override to add more detailed logging
        print(f"HTTP Server: {format%args}")

class HTTPServerThread(threading.Thread):
    def __init__(self, port=8000):
        super().__init__(daemon=True)
        self.port = port
        self.server = None
        self.is_running = threading.Event()

    def run(self):
        try:
            server_address = ('', self.port)
            self.server = HTTPServer(server_address, HealthCheckHandler)
            self.is_running.set()
            print(f"HTTP server running on http://localhost:{self.port}")
            self.server.serve_forever()
        except Exception as e:
            print(f"HTTP Server error: {e}")
            self.is_running.clear()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.is_running.clear()

async def check_http_server():
    """检查HTTP服务是否就绪"""
    async with aiohttp.ClientSession() as session:
        for i in range(10):  # Reduced number of retries, but added better logging
            try:
                async with session.get('http://localhost:8000/healthz') as resp:
                    if resp.status == 200:
                        print("HTTP server health check successful")
                        return True
                    print(f"HTTP server returned status {resp.status}")
            except aiohttp.ClientError as e:
                print(f"Attempt {i+1}/10: HTTP server not ready yet: {e}")
            await asyncio.sleep(1)
        return False

async def monitor_cloudflared(process):
    """监控cloudflared进程并提取URL"""
    url = None
    try:
        while True:
            line = process.stdout.readline()
            if not line:
                break
            
            line_str = line if isinstance(line, str) else line.decode()
            print(f"Cloudflared output: {line_str.strip()}")
            
            if 'trycloudflare.com' in line_str.lower():
                url = line_str.strip()
                print("\n" + "="*50)
                print("CLOUDFLARED PUBLIC URL:")
                print(url)
                print("="*50 + "\n")
                break
            
            await asyncio.sleep(0.1)
    except Exception as e:
        print(f"Error monitoring cloudflared: {e}")
    return url

async def start_cloudflared():
    """启动并监控cloudflared"""
    print("\nStarting cloudflared tunnel...")
    try:
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Redirect stderr to stdout for better logging
            bufsize=1,
            universal_newlines=True
        )
        
        # Set a timeout for getting the URL
        try:
            url = await asyncio.wait_for(monitor_cloudflared(process), timeout=20.0)
            if not url:
                raise RuntimeError("Failed to get cloudflared URL")
            return process, url
        except asyncio.TimeoutError:
            process.terminate()
            raise RuntimeError("Timeout waiting for cloudflared URL")
            
    except Exception as e:
        print(f"Error starting cloudflared: {str(e)}")
        return None, None

async def websocket_handler(websocket, path):
    print(f"New WebSocket connection established: {websocket.remote_address}")
    try:
        await download_manager.register(websocket)
        async for message in websocket:
            try:
                async with asyncio.timeout(5.0):
                    print(f"Received WebSocket message: {message}")
                    # Add your message handling logic here
                    pass
            except asyncio.TimeoutError:
                print("Message handling timeout")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await download_manager.unregister(websocket)
        print(f"WebSocket connection closed: {websocket.remote_address}")

async def start_websocket_server():
    print("Starting WebSocket server...")
    server = await websockets.serve(websocket_handler, "localhost", 8765)
    print("WebSocket server is running on ws://localhost:8765")
    await server.wait_closed()

async def main(magnet_link, save_path, huggingface_token):
    print("Starting main application...")
    
    # Start HTTP server in a separate thread
    http_server = HTTPServerThread()
    http_server.start()
    
    try:
        # Wait for HTTP server to start
        if not await asyncio.wait_for(check_http_server(), timeout=10.0):
            raise RuntimeError("HTTP server failed to start")
        
        print("HTTP server is ready")
        
        # Start cloudflared
        cloudflared_process, cloudflared_url = await start_cloudflared()
        if not cloudflared_process:
            raise RuntimeError("Failed to start cloudflared")
        
        print("Cloudflared tunnel is ready")

        # Create and start the download task
        download_task = asyncio.create_task(
            start_download(magnet_link, save_path, huggingface_token)
        )
        
        # Start WebSocket server
        websocket_task = asyncio.create_task(start_websocket_server())
        
        # Wait for tasks to complete
        await asyncio.gather(
            download_task,
            websocket_task
        )
        
    except asyncio.TimeoutError:
        print("Timeout occurred while starting services")
        raise
    except Exception as e:
        print(f"Error in main: {e}")
        raise
    finally:
        # Cleanup
        print("Cleaning up resources...")
        http_server.stop()
        if 'cloudflared_process' in locals() and cloudflared_process:
            cloudflared_process.terminate()
            try:
                cloudflared_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cloudflared_process.kill()

def signal_handler(signum, frame):
    print(f"\nReceived signal {signum}. Shutting down gracefully...")
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    magnet_link = "magnet:?xt=urn:btih:UPDH7IQHVPOHYBBJQYFSTUEEI6G2AD6K&dn=&tr=http%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=udp%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=http%3A%2F%2Ftracker.openbittorrent.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=http%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftracker.publicbt.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker.prq.to%2Fannounce&tr=http%3A%2F%2Fopen.acgtracker.com%3A1096%2Fannounce&tr=https%3A%2F%2Ft-115.rhcloud.com%2Fonly_for_ylbud&tr=http%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=http%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=udp%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftr.bangumi.moe%3A6969%2Fannounce"
    save_path = "Torrent/"
    
    if len(sys.argv) != 2:
        print("Error: Huggingface token not provided")
        print("Usage: python3 server2.py <huggingface_token>")
        sys.exit(1)
        
    huggingface_token = sys.argv[1]
    
    print(f'Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")}')
    print(f"Current User's Login: map9876543")
    
    try:
        asyncio.run(main(magnet_link, save_path, huggingface_token))
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)