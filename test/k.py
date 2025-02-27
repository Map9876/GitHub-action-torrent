import libtorrent as lt
import time
import os
import sys
import json
from huggingface_hub import HfApi, login
from datetime import datetime, UTC
import asyncio
from dler import download_manager  # 确保此行存在

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
        self.metadata_file = os.path.join(save_path, "torrent_metadata.json")
        self.progress_file = os.path.join(save_path, "download_progress.json")
        self.huggingface_token = huggingface_token
        self.api = HfApi()
        self.USERNAME = "servejjjhjj"
        self.REPO_NAME = 'mp4-dataset'
        self.REPO_TYPE = 'dataset'
        self.session = lt.session()
        
        self.UPLOAD_INTERVAL = 60  # 5小时上传一次
        self.STATUS_UPDATE_INTERVAL = 1  # 1秒更新一次状态
        
        os.makedirs(self.pieces_folder, exist_ok=True)
        os.makedirs(self.save_path, exist_ok=True)

        settings = {
            'alert_mask': lt.alert.category_t.all_categories,
            'enable_dht': True,
            'enable_lsd': True,
            'enable_upnp': True,
            'enable_natpmp': True,
            'download_rate_limit': 0,
            'upload_rate_limit': 0,
            'alert_queue_size': 10000,
        }
        self.session.apply_settings(settings)

    def load_progress_from_hf(self):
        try:
            progress_content = self.api.download_file(
                repo_id=f"{self.USERNAME}/{self.REPO_NAME}",
                filename="download_progress.json"
            )
            progress_data = json.loads(progress_content)
            print(f"Loaded progress: {len(progress_data['downloaded_pieces'])} pieces downloaded")
            return progress_data
        except Exception as e:
            print(f"No previous progress found on HuggingFace: {e}")
            return None

    def save_progress_to_hf(self, handle, last_uploaded_piece):
        progress_data = {
            "last_uploaded_piece": last_uploaded_piece,
            "downloaded_pieces": [i for i in range(handle.status().torrent_file.num_pieces()) 
                                if handle.have_piece(i)],
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "total_pieces": handle.status().torrent_file.num_pieces()
        }
        
        with open(self.progress_file, 'w') as f:
            json.dump(progress_data, f)
        
        try:
            self.api.upload_file(
                path_or_fileobj=self.progress_file,
                path_in_repo="test/download_progress.json",
                repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                repo_type=self.REPO_TYPE
            )
            print(f"Progress saved at: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}")
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
            
            # 获取状态字符串
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
                # 获取所有文件的进度
                for file_index in range(torrent_file.num_files()):
                    try:
                        file_path = torrent_file.files().file_path(file_index)
                        file_size = torrent_file.files().file_size(file_index)
                        downloaded = file_progress[file_index]
                        
                        # 安全计算下载速度
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

                # 安全计算总进度
                total_progress = 0
                if total_size > 0:
                    total_progress = (total_downloaded / total_size * 100)

                # 更新UI
                download_manager.update_status(
                    files_status,
                    status.num_peers,
                    total_progress
                )

                # 打印命令行进度
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

        # 设置 DHT
        self.session.add_dht_router("router.bittorrent.com", 6881)
        self.session.add_dht_router("router.utorrent.com", 6881)
        self.session.add_dht_router("dht.transmissionbt.com", 6881)

        # 创建 torrent handle
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

        # 从之前的进度恢复
        progress_data = self.load_progress_from_hf()
        last_uploaded_piece = -1
        if progress_data:
            print("Resuming from previous progress...")
            last_uploaded_piece = progress_data['last_uploaded_piece']
            for piece in progress_data['downloaded_pieces']:
                handle.piece_priority(piece, 0)

        last_upload_time = time.time()
        last_status_update = time.time()

        while not handle.status().is_seeding:
            current_time = time.time()
            
            # 更新UI状态
            if current_time - last_status_update >= self.STATUS_UPDATE_INTERVAL:
              
                self.update_ui_status(handle)
                last_status_update = current_time
            
            # 处理HuggingFace上传
            if current_time - last_upload_time >= self.UPLOAD_INTERVAL:
                print(f"\nUploading pieces {last_uploaded_piece + 1} to {current_piece}...")
                status = handle.status()
                current_piece = int(status.progress * torrent_file.num_pieces())
                
                if current_piece > last_uploaded_piece:
                    print(f"\nUploading pieces {last_uploaded_piece + 1} to {current_piece}...")
                    for piece_index in range(last_uploaded_piece + 1, current_piece + 1):
                        if handle.have_piece(piece_index):
                            piece_path = await self.save_piece(handle, piece_index)
                            if piece_path:
                                try:
                                    self.api.upload_file(
                                        path_or_fileobj=piece_path,
                                        path_in_repo=f"test/pieces/piece_{piece_index}.dat",
                                        repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                                        repo_type=self.REPO_TYPE
                                    )
                                    os.remove(piece_path)
                                    print(f"Uploaded piece {piece_index}")
                                except Exception as e:
                                    print(f"\nError uploading piece {piece_index}: {e}")
                    
                    last_uploaded_piece = current_piece
                    self.save_progress_to_hf(handle, last_uploaded_piece)
                
                last_upload_time = current_time

            # 处理alert
            alerts = self.session.pop_alerts()
            for alert in alerts:
                if alert.category() & lt.alert.category_t.error_notification:
                    print(f"\nError: {alert.message()}")

            await asyncio.sleep(1)

        print('\nDownload complete!')
        self.save_progress_to_hf(handle, torrent_file.num_pieces() - 1)

async def start_download(magnet_link, save_path, huggingface_token):
    downloader = TorrentDownloader(magnet_link, save_path, huggingface_token)
    await downloader.download()