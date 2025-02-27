import libtorrent as lt
import time
import os
import sys
import json
import zipfile
import shutil
from huggingface_hub import HfApi, login
from datetime import datetime, timezone
import asyncio
from dler import download_manager


def format_size(size):
    """格式化文件大小"""
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

        # 配置libtorrent会话
        settings = {
            'alert_mask': lt.alert.category_t.all_categories,
            'enable_dht': True,
            'enable_lsd': True,
            'enable_upnp': True,
            'enable_natpmp': True,
            'download_rate_limit': 5 * 1024 * 1024,  # 5 MB/s 的速率限制
            'upload_rate_limit': 0,  # 0 表示无限制
            'alert_queue_size': 10000,
        }
        self.session.apply_settings(settings)

    async def save_piece(self, handle, piece_index):
        """异步保存piece到文件"""
        try:
            # 创建 Future 对象用于等待回调
            piece_future = asyncio.Future()

            # 定义回调函数
            def piece_read_callback(piece_buffer):
                if not piece_future.done():
                    piece_future.set_result(piece_buffer)

            # 调用 read_piece
            handle.read_piece(piece_index)

            # 等待回调完成，设置超时时间
            try:
            # 循环处理alerts直到获取到所需的piece数据
                async with asyncio.timeout(10):  # 10秒超时
                    while not piece_future.done():
                        alerts = self.session.pop_alerts()
                        for alert in alerts:
                            if isinstance(alert, lt.read_piece_alert):
                                if alert.piece == piece_index and not piece_future.done():
                                    piece_future.set_result(alert.buffer)
                        await asyncio.sleep(0.1)

                piece_buffer = await piece_future
                if not piece_buffer:
                    print(f"No data received for piece {piece_index}")
                    return None



            # 保存 piece 数据到文件
                piece_path = os.path.join(self.pieces_folder, f"piece_{piece_index}.dat")
                with open(piece_path, 'wb') as f:
                    f.write(piece_buffer)

                return piece_path
            except asyncio.TimeoutError:
                print(f"Timeout reading piece {piece_index}")
                return None


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
                self.api.upload_file(
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
                with open(self.progress_file, 'r') as f:
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
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
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
        """主下载逻辑"""
        print(f'Current Date and Time (UTC): {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}')

        # 登录到 Hugging Face
        try:
            login(token=self.huggingface_token)
            print("Successfully logged in to Hugging Face")
        except Exception as e:
            print(f"Login failed: {e}")
            return

        # 确保仓库存在
        try:
            repo_url = self.api.create_repo(
                repo_id=f"{self.USERNAME}/{self.REPO_NAME}",
                repo_type=self.REPO_TYPE,
                private=False,
                exist_ok=True  # 允许仓库已存在
            )
            print(f"Repository ready at: {repo_url}")
        except Exception as e:
            print(f'Repository error: {e}')
            return

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
        torrent_info = handle.get_torrent_info()
        total_pieces = torrent_info.num_pieces()
        piece_length = torrent_info.piece_length()
        
        print(f"Total size: {format_size(torrent_info.total_size())}")
        print(f"Number of pieces: {total_pieces}")
        print(f"Piece length: {format_size(piece_length)}")

        # 从本地加载进度
        progress_data = self.load_progress_from_file()
        last_uploaded_piece = -1
        if progress_data:
            print("Resuming from previous progress...")
            last_uploaded_piece = progress_data.get('last_uploaded_piece', -1)
            print(f"Last uploaded piece: {last_uploaded_piece}")

        last_upload_time = time.time() - self.UPLOAD_INTERVAL  # 确保第一批pieces会被上传
        last_status_update = time.time()
        successful_pieces = []
        last_processed_piece = last_uploaded_piece

        while not handle.status().is_seeding:
            current_time = time.time()
            status = handle.status()
            
            # 更新状态显示
            if current_time - last_status_update >= self.STATUS_UPDATE_INTERVAL:
                self.update_ui_status(handle)
                last_status_update = current_time

            # 计算当前下载进度
            current_piece = int(status.progress * total_pieces)

            # 处理新下载的pieces
            for piece_index in range(last_processed_piece + 1, current_piece + 1):
                if handle.have_piece(piece_index):
                    print(f"\nProcessing piece {piece_index}")
                    piece_path = await self.save_piece(handle, piece_index)
                    if piece_path:
                        successful_pieces.append(piece_index)
                        print(f"Piece {piece_index} saved successfully")
                    await asyncio.sleep(0.1)
            
            last_processed_piece = current_piece

            # 检查是否需要上传
            if successful_pieces and (
                current_time - last_upload_time >= self.UPLOAD_INTERVAL or 
                len(successful_pieces) >= self.PIECES_PER_ARCHIVE
            ):
                print(f"\nPreparing to upload {len(successful_pieces)} pieces...")
                
                # 对pieces进行排序和分组
                successful_pieces.sort()
                chunks = []
                current_chunk = []
                
                for piece in successful_pieces:
                    if not current_chunk or piece == current_chunk[-1] + 1:
                        current_chunk.append(piece)
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = [piece]
                
                if current_chunk:
                    chunks.append(current_chunk)

                print(f"Created {len(chunks)} groups of continuous pieces")

                # 处理每个分组
                uploaded_pieces = set()
                for chunk in chunks:
                    start_piece = chunk[0]
                    end_piece = chunk[-1]
                    
                    print(f"\nCreating archive for pieces {start_piece} to {end_piece}")
                    archive_path = self.create_piece_archive(start_piece, end_piece, chunk)
                    
                    if archive_path:
                        try:
                            if await self.upload_piece_archive(archive_path, start_piece, end_piece):
                                print(f"Successfully uploaded archive {start_piece} to {end_piece}")
                                uploaded_pieces.update(chunk)
                                last_uploaded_piece = max(last_uploaded_piece, end_piece)
                                self.save_progress_to_file(handle, last_uploaded_piece)
                            else:
                                print(f"Failed to upload archive {start_piece} to {end_piece}")
                        except Exception as e:
                            print(f"Error during upload: {e}")

                # 移除已上传的pieces
                successful_pieces = [p for p in successful_pieces if p not in uploaded_pieces]
                print(f"Remaining pieces after upload: {len(successful_pieces)}")
                
                last_upload_time = current_time

            # 处理错误信息
            alerts = self.session.pop_alerts()
            for alert in alerts:
                if alert.category() & lt.alert.category_t.error_notification:
                    print(f"\nError: {alert.message()}")

            await asyncio.sleep(1)

        print('\nDownload complete!')
        
        # 处理剩余的pieces
        if successful_pieces:
            print(f"\nUploading final {len(successful_pieces)} pieces")
            successful_pieces.sort()
            start_piece = successful_pieces[0]
            end_piece = successful_pieces[-1]
            archive_path = self.create_piece_archive(start_piece, end_piece, successful_pieces)
            if archive_path:
                if await self.upload_piece_archive(archive_path, start_piece, end_piece):
                    print(f"Successfully uploaded final archive {start_piece} to {end_piece}")
                    self.save_progress_to_file(handle, end_piece)

        # 清理临时文件夹
        print("\nCleaning up temporary files...")
        if os.path.exists(self.pieces_folder):
            shutil.rmtree(self.pieces_folder)
        if os.path.exists(self.temp_folder):
            shutil.rmtree(self.temp_folder)
        print("Cleanup complete")

async def start_download(magnet_link, save_path, huggingface_token):
    """启动下载任务"""
    downloader = TorrentDownloader(magnet_link, save_path, huggingface_token)
    await downloader.download()