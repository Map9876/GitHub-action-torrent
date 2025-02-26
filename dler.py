import asyncio
import json
from datetime import datetime

class DownloadManager:
    def __init__(self):
        self.connected_clients = set()
        self.current_status = {
            "files": [],
            "peers": 0,
            "total_progress": 0,
            "start_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

    def update_status(self, files_status, peers, total_progress):
        """更新当前下载状态并广播给所有连接的客户端"""
        self.current_status = {
            "files": files_status,
            "peers": peers,
            "total_progress": total_progress,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }
        asyncio.create_task(self.broadcast_status())

    async def register(self, websocket):
        """注册新的WebSocket客户端"""
        self.connected_clients.add(websocket)
        await websocket.send(json.dumps(self.current_status))

    async def unregister(self, websocket):
        """注销WebSocket客户端"""
        self.connected_clients.remove(websocket)

    async def broadcast_status(self):
        """向所有连接的客户端广播状态更新"""
        if self.connected_clients:
            message = json.dumps(self.current_status)
            await asyncio.gather(
                *[client.send(message) for client in self.connected_clients],
                return_exceptions=True
            )

    def get_current_status(self):
        """获取当前状态"""
        return self.current_status

# 创建全局下载管理器实例
download_manager = DownloadManager()