import libtorrent as lt
import time
import os
import sys
import json
import zipfile
import shutil
from huggingface_hub import HfApi, login
from datetime import datetime, UTC
import asyncio
from dler import download_manager

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

class TorrentDownloader:
    def __init__(self, magnet_link, save_path, huggingface_token):
        self.magnet_link = magnet_link
        self.save_path = save_path
        self.pieces_folder = os.path.join(save_path, "pieces")
        self.temp_folder = os.path.join(save_path, "temp")
        self.metadata_file = os.path.join(save_path, "torrent_metadata.json")
        self.progress_file = os.path.join(save_path, "download_progress.json")
        self.huggingface_token = huggingface_token
        self.api = HfApi()
        self.USERNAME = "servejjjhjj"
        self.REPO_NAME = 'mp4-dataset'
        self.REPO_TYPE = 'dataset'
        self.session = lt.session()
        
        # 配置参数
        self.UPLOAD_INTERVAL = 60  # 60秒检查一次是否需要上传
        self.STATUS_UPDATE_INTERVAL = 1  # 1秒更新一次状态
        self.PIECES_PER_ARCHIVE = 100  # 每个压缩包包含的piece数量
        self.MAX_RETRIES = 3  # 上传重试次数
        
        # 创建必要的目录
        for folder in [self.pieces_folder, self.temp_folder]:
            os.makedirs(folder, exist_ok=True)

        settings = {
            'alert_mask': lt.alert.category_t.all_categories,
            'enable_dht': True,
            'enable_lsd': True,
            'enable_upnp': True,
            'enable_natpmp': True,
            'download_rate_limit': 5 * 1024 * 1024,  # 5 MB/s 的速率限制
            'upload_rate_limit': 0,
            'alert_queue_size': 10000,
        }
        self.session.apply_settings(settings)

    async def save_piece(self, handle, piece_index):
        """异步保存piece到文件"""
        try:
            piece_future = asyncio.Future()
            
            def piece_read_callback(piece_buffer):
                if not piece_future.done():
                    piece_future.set_result(piece_buffer)
            
            handle.read_piece(piece_index, piece_read_callback)
            
            try:
                piece_data = await asyncio.wait_for(piece_future, timeout=10.0)
            except asyncio.TimeoutError:
                print(f"Timeout reading piece {piece_index}")
                return None

            if piece_data is None:
                print(f"Failed to read piece {piece_index}")
                return None
                
            piece_path = os.path.join(self.pieces_folder, f"piece_{piece_index}.dat")
            with open(piece_path, 'wb') as f:
                f.write(piece_data)
            return piece_path

        except Exception as e:
            print(f"Error saving piece {piece_index}: {e}")
            return None

    def create_piece_archive(self, start_piece, end_piece, successful_pieces):
        """将多个piece打包成zip文件"""
        try:
            archive_name = f"pieces_{start_piece}_to_{end_piece}.zip"
            archive_path = os.path.join(self.temp_folder, archive_name)
            
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for piece_index in successful_pieces:
                    piece_path = os.path.join(self.pieces_folder, f"piece_{piece_index}.dat")
                    if os.path.exists(piece_path):
                        zf.write(piece_path, f"piece_{piece_index}.dat")
                        os.remove(piece_path)  # 删除已打包的piece文件

            return archive_path
        except Exception as e:
            print(f"Error creating archive: {e}")
            return None

    async def upload_piece_archive(self, archive_path, start_piece, end_piece):
        """上传piece压缩包到HuggingFace"""
        for attempt in range(self.MAX_RETRIES):
            try:
                self.api.ile(
                    path_or_fileobj=archive_path,
                    path_in_repo=f"test/pieces/archive_{start_piece}_to_{end_piece}.zip",
                    repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                    repo_type=self.REPO_TYPE
                )
                os.remove(archive_path)
                return True
            except Exception as e:
                print(f"Upload attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(5)  # 等待一段时间后重试
        return False

    def load_progress_from_file(self):
        """从本地文件加载下载进度"""
        try:
            if os.path.exists(self.progress_file):
                with (self.progress_file, 'r') as f:
                    progress_data = json.load(f)
                print(f"Loaded progress: {len(progress_data['downloaded_pieces'])} pieces downloaded")
                return progress_data
        except Exception as e:
            print(f"Error loading progress: {e}")
        return None

    def save_progress_to_file(self, handle, last_uploaded_piece):
        """保存下载进度到本地文件"""
        progress_data = {
            "last_uploaded_piece": last_uploaded_piece,
            "downloaded_pieces": [i for i in range(handle.status().torrent_file.num_pieces()) 
                                if handle.have_piece(i)],
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "total_pieces": handle.status().torrent_file.num_pieces()
        }
        
        try:
            with open(self.progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)
            
            # 上传进度文件到HuggingFace
            self.api.upload_file(
                path_or_fileobj=self.progress_file,
                path_in_repo="test/download_progress.json",
                repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                repo_type=self.REPO_TYPE
            )
        except Exception as e:
            print(f"Error saving progress: {e}")
        
        return progress_data

    def update_ui_status(self, handle):
        """更新UI状态"""
        try:
            status = handle.status()
            torrent_file = status.torrent_file
            
            if not torrent_file:
                return
            
            state_map = {
                0: 'queued',
                1: 'checking',
                2: 'downloading metadata',
                3: 'downloading',
                4: 'finished',
                5: 'seeding',
                6: 'allocating'
            }
            state_str = state_map.get(status.state, 'unknown')
            
            file_progress = handle.file_progress()
            files_status = []
            total_downloaded = 0
            total_size = 0

            try:
                for file_index in range(torrent_file.num_files()):
                    try:
                        file_path = torrent_file.files().file_path(file_index)
                        file_size = torrent_file.files().file_size(file_index)
                        downloaded = file_progress[file_index]
                        
                        file_speed = 0
                        if torrent_file.total_size() > 0:
                            file_speed = (status.download_rate * file_size) / torrent_file.total_size()
                        
                        files_status.append({
                            "index": file_index,
                            "path": file_path,
                            "size": file_size,
                            "downloaded": downloaded,
                            "speed": file_speed,
                            "progress": (downloaded / file_size * 100) if file_size > 0 else 0,
                            "state": state_str
                        })
                        
                        total_downloaded += downloaded
                        total_size += file_size
                    except Exception as e:
                        print(f"Error processing file {file_index}: {e}")
                        continue

                total_progress = 0
                if total_size > 0:
                    total_progress = (total_downloaded / total_size * 100)

                download_manager.update_status(
                    files_status,
                    status.num_peers,
                    total_progress
                )

                print(f'\rProgress: {total_progress:.2f}% '
                      f'Speed: {format_size(status.download_rate)}/s '
                      f'Peers: {status.num_peers} '
                      f'State: {state_str}', end='', flush=True)

            except Exception as e:
                print(f"\nError calculating progress: {e}")

        except Exception as e:
            print(f"\nError in update_ui_status: {e}")

    async def download(self):
        print(f'Current Date and Time (UTC): {datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")}')
        
        login(token=self.huggingface_token)

        try:
            repo_url = self.api.create_repo(
                repo_id=f"{self.USERNAME}/{self.REPO_NAME}",
                repo_type=self.REPO_TYPE,
                private=False
            )
            print(f"Repository URL: {repo_url}")
        except Exception as e:
            print(f'Repository note: {e}')

        self.session.add_dht_router("router.bittorrent.com", 6881)
        self.session.add_dht_router("router.utorrent.com", 6881)
        self.session.add_dht_router("dht.transmissionbt.com", 6881)

        atp = lt.add_torrent_params()
        atp.url = self.magnet_link
        atp.save_path = self.save_path
        handle = self.session.add_torrent(atp)

        print('Downloading metadata...')
        while not handle.status().has_metadata:
            try:
                self.update_ui_status(handle)
            except Exception as e:
                print(f"Error during metadata download: {e}")
            await asyncio.sleep(1)

        print('\nGot metadata, starting download...')
        torrent_file = handle.status().torrent_file
        
        if not torrent_file:
            print("Error: Failed to get torrent info")
            return

        print(f"Total size: {format_size(torrent_file.total_size())}")
        print(f"Number of pieces: {torrent_file.num_pieces()}")

        progress_data = self.load_progress_from_file()
        last_uploaded_piece = -1
        if progress_data:
            print("Resuming from previous progress...")
            last_uploaded_piece = progress_data.get('last_uploaded_piece', -1)

        last_upload_time = time.time()
        last_status_update = time.time()
        current_piece = -1
        pending_pieces = []

        while not handle.status().is_seeding:
            current_time = time.time()
            
            if current_time - last_status_update >= self.STATUS_UPDATE_INTERVAL:
                self.update_ui_status(handle)
                last_status_update = current_time
            
            status = handle.status()
            current_piece = int(status.progress * torrent_file.num_pieces())
            
            if current_time - last_upload_time >= self.UPLOAD_INTERVAL:
                if current_piece > last_uploaded_piece:
                    print(f"\nProcessing pieces {last_uploaded_piece + 1} to {current_piece}")
                    successful_pieces = []
                    
                    # 保存新的pieces
                    for piece_index in range(last_uploaded_piece + 1, current_piece + 1):
                        if handle.have_piece(piece_index):
                            piece_path = await self.save_piece(handle, piece_index)
                            if piece_path:
                                successful_pieces.append(piece_index)
                                print(f"Saved piece {piece_index}")
                            await asyncio.sleep(0.1)  # 避免过快读取
                    
                    # 如果有足够的pieces或者是最后一批，创建压缩包
                    if len(successful_pieces) >= self.PIECES_PER_ARCHIVE or current_piece == torrent_file.num_pieces() - 1:
                        start_piece = successful_pieces[0]
                        end_piece = successful_pieces[-1]
                        
                        archive_path = self.create_piece_archive(start_piece, end_piece, successful_pieces)
                        if archive_path:
                            print(f"Created archive for pieces {start_piece} to {end_piece}")
                            if await self.upload_piece_archive(archive_path, start_piece, end_piece):
                                print(f"Successfully uploaded archive {start_piece} to {end_piece}")
                                last_uploaded_piece = end_piece
                                self.save_progress_to_file(handle, last_uploaded_piece)
                
                last_upload_time = current_time

            alerts = self.session.pop_alerts()
            for alert in alerts:
                if alert.category() & lt.alert.category_t.error_notification:
                    print(f"\nError: {alert.message()}")

            await asyncio.sleep(1)

        print('\nDownload complete!')
        # 处理剩余的pieces
        if os.path.exists(self.pieces_folder):
            shutil.rmtree(self.pieces_folder)
        if os.path.exists(self.temp_folder):
            shutil.rmtree(self.temp_folder)

async def start_download(magnet_link, save_path, huggingface_token):
    downloader = TorrentDownloader(magnet_link, save_path, huggingface_token)
    await downloader.download()
