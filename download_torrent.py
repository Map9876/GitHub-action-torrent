import libtorrent as lt
import os
import asyncio
import json
import time
from huggingface_hub import HfApi, login
from rich.console import Console
from rich.progress import Progress
from rich.tree import Tree
import websockets
import shutil
from downloader import download_manager

class TorrentDownloader:
    def __init__(self, magnet_link, save_path, huggingface_token):
        self.magnet_link = magnet_link
        self.save_path = save_path
        self.huggingface_token = huggingface_token
        self.api = HfApi()
        self.USERNAME = "servejjjhjj"  # 使用当前用户的登录名
        self.REPO_NAME = 'mp4-dataset'
        self.REPO_TYPE = 'dataset'
        self.session = lt.session()
        self.handle = None
        self.progress = Progress()
        self.console = Console()
        self.progress_file = "progress.json"
        self.pieces_folder = os.path.join(save_path, "pieces")
        os.makedirs(self.pieces_folder, exist_ok=True)

    def load_progress(self):
        if os.path.exists(self.progress_file):
            with open(self.progress_file, "r") as f:
                return json.load(f)
        return {}

    def save_progress(self, progress):
        with open(self.progress_file, "w") as f:
            json.dump(progress, f)

    async def ensure_repo_exists(self):
        """确保仓库存在，如果不存在则创建"""
        try:
            repo_url = self.api.create_repo(
                repo_id=f"{self.USERNAME}/{self.REPO_NAME}",
                repo_type=self.REPO_TYPE,
                private=False
            )
            self.console.print(f'Created new repository: {repo_url}')
            return repo_url
        except Exception as e:
            self.console.print(f'[red]have with repository already: {str(e)}')
            return f"https://huggingface.co/{self.USERNAME}/{self.REPO_NAME}"

    async def handle_piece_finished(self, alert, websocket):
        piece_index = alert.piece_index
        piece_length = self.handle.get_torrent_info().piece_length()
        piece_data = bytearray(piece_length)
        self.handle.read_piece(piece_index)

        while True:
            alerts = self.session.pop_alerts()
            for alert in alerts:
                if isinstance(alert, lt.read_piece_alert):
                    if alert.piece == piece_index:
                        piece_data = alert.buffer
                        backup_path = os.path.join(self.pieces_folder, f"piece_{piece_index}.dat")
                        with open(backup_path, "wb") as f:
                            f.write(piece_data)
                        try:
                            self.api.upload_file(
                                path_or_fileobj=backup_path,
                                path_in_repo=f"pieces/piece_{piece_index}.dat",
                                repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                                repo_type=self.REPO_TYPE
                            )
                            os.remove(backup_path)
                            await websocket.send(json.dumps({"piece_index": piece_index, "status": "backed_up"}))
                        except Exception as e:
                            self.console.print(f'[red]Error uploading piece {piece_index}: {str(e)}')
                        return
            await asyncio.sleep(0.1)

    async def start(self):
        try:
            self.console.print(f'Your username is: {self.USERNAME}')
            login(token=self.huggingface_token)

            # 确保仓库存在
            repo_url = await self.ensure_repo_exists()

            params = {
                'save_path': self.save_path,
                'storage_mode': lt.storage_mode_t.storage_mode_sparse,
            }

            # Load previous progress if available
            progress_data = self.load_progress()
            if progress_data:
                try:
                    self.session.load_state(progress_data.get("session_state", b""))
                    self.handle = lt.add_magnet_uri(self.session, self.magnet_link, params)
                    self.handle.set_sequential_download(1)
                except Exception as e:
                    self.console.print(f'[yellow]Warning: Could not load previous state: {str(e)}')
                    self.handle = lt.add_magnet_uri(self.session, self.magnet_link, params)
                    self.handle.set_sequential_download(1)
            else:
                self.handle = lt.add_magnet_uri(self.session, self.magnet_link, params)
                self.handle.set_sequential_download(1)

            self.session.start_dht()

            self.console.print('Downloading Metadata...')
            while not self.handle.has_metadata():
                await asyncio.sleep(1)
            
            self.console.print('Got Metadata, Starting Torrent Download...')
            torrent_info = self.handle.get_torrent_info()
            
            files = sorted([
                {"index": i, "path": torrent_info.files().file_path(i), "size": torrent_info.files().file_size(i)}
                for i in range(torrent_info.num_files())
            ], key=lambda x: x["size"], reverse=True)

            tree = Tree("Files in torrent")
            tasks = {}
            for file_info in files:
                tasks[file_info["index"]] = self.progress.add_task(
                    f"[green]{file_info['path']}", 
                    total=file_info["size"]
                )
                tree.add(f"{file_info['path']} ({self.format_size(file_info['size'])})")

            self.console.print(tree)
            download_manager.downloads = [
                {"index": file_info["index"], "size": file_info["size"], "downloaded": 0, "speed": 0}
                for file_info in files
            ]

            async with websockets.connect("ws://localhost:8765") as websocket:
                last_upload_time = time.time()
                while True:
                    try:
                        alerts = self.session.pop_alerts()
                        for alert in alerts:
                            if isinstance(alert, lt.piece_finished_alert):
                                await self.handle_piece_finished(alert, websocket)
                        
                        s = self.handle.status()
                        for file_info in files:
                            completed = self.handle.file_progress()[file_info["index"]]
                            self.progress.update(tasks[file_info["index"]], completed=completed)
                            download = download_manager.downloads[file_info["index"]]
                            download["downloaded"] = completed
                            download["speed"] = s.download_rate / 1000
                            downloaded_size = self.format_size(completed)
                            total_size = self.format_size(file_info["size"])
                            self.console.print(
                                f'Downloading {file_info["path"]}: {downloaded_size} / {total_size} '
                                f'(down: {s.download_rate / 1000:.1f} kB/s)'
                            )

                        message = json.dumps(download_manager.get_download_data())
                        await websocket.send(message)
                        
                        if time.time() - last_upload_time >= 5 * 3600:  # 每5小时
                            await self.upload_progress()
                            last_upload_time = time.time()

                        # 检查是否所有文件都下载完成
                        if all(d["downloaded"] == d["size"] for d in download_manager.downloads):
                            self.console.print('[green]Download Complete!')
                            break

                        await asyncio.sleep(1)

                    except websockets.ConnectionClosed:
                        self.console.print('[yellow]WebSocket connection closed, attempting to reconnect...')
                        await asyncio.sleep(5)  # 等待5秒后重试
                        continue
                    except Exception as e:
                        self.console.print(f'[red]Error during download: {str(e)}')
                        await asyncio.sleep(1)  # 发生错误时短暂暂停
                        continue

        except Exception as e:
            self.console.print(f'[red]Critical error: {str(e)}')
            raise

    async def upload_progress(self):
        try:
            session_state = self.session.save_state()
            progress_data = {
                "session_state": session_state
            }
            self.save_progress(progress_data)
            backup_path = os.path.join(self.save_path, "progress_backup.json")
            shutil.copyfile(self.progress_file, backup_path)
            self.api.upload_file(
                path_or_fileobj=backup_path,
                path_in_repo="progress_backup.json",
                repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                repo_type=self.REPO_TYPE
            )
            os.remove(backup_path)
        except Exception as e:
            self.console.print(f'[red]Error uploading progress: {str(e)}')

    @staticmethod
    def format_size(size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024

async def start_download(magnet_link, save_path, huggingface_token):
    downloader = TorrentDownloader(magnet_link, save_path, huggingface_token)
    await downloader.start()