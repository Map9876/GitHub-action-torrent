import libtorrent as lt
import time
import os
import sys
import json
from huggingface_hub import HfApi, login
from datetime import datetime
import asyncio
import hashlib
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
        self.metadata_file = os.path.join(save_path, "torrent_metadata.json")
        self.progress_file = os.path.join(save_path, "download_progress.json")
        self.huggingface_token = huggingface_token
        self.api = HfApi()
        self.USERNAME = "servejjjhjj"
        self.REPO_NAME = 'mp4-dataset'
        self.REPO_TYPE = 'dataset'
        self.session = lt.session()
        self.UPLOAD_INTERVAL = 5 * 3600  # 5小时
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
            "downloaded_pieces": [i for i in range(handle.get_torrent_info().num_pieces()) 
                                if handle.have_piece(i)],
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "total_pieces": handle.get_torrent_info().num_pieces()
        }
        
        with open(self.progress_file, 'w') as f:
            json.dump(progress_data, f)
        
        try:
            self.api.upload_file(
                path_or_fileobj=self.progress_file,
                path_in_repo="download_progress.json",
                repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                repo_type=self.REPO_TYPE
            )
            print(f"Progress saved at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"Error saving progress: {e}")
        return progress_data

    def update_download_status(self, handle, last_uploaded_piece):
        s = handle.status()
        torrent_info = handle.get_torrent_info()
        file_progress = handle.file_progress()
        
        files_status = []
        total_downloaded = 0
        total_size = 0
        
        for file_index in range(torrent_info.num_files()):
            file_entry = torrent_info.files()
            file_path = file_entry.file_path(file_index)
            file_size = file_entry.file_size(file_index)
            downloaded = file_progress[file_index]
            
            file_speed = (s.download_rate * file_size) / torrent_info.total_size() if torrent_info.total_size() > 0 else 0
            
            files_status.append({
                "index": file_index,
                "path": file_path,
                "size": file_size,
                "downloaded": downloaded,
                "speed": file_speed,
                "progress": (downloaded / file_size * 100) if file_size > 0 else 0
            })
            
            total_downloaded += downloaded
            total_size += file_size

        download_manager.update_status(
            files_status,
            s.num_peers,
            (total_downloaded / total_size * 100) if total_size > 0 else 0
        )

    async def save_piece(self, handle, piece_index):
        try:
            handle.read_piece(piece_index)
            for _ in range(100):  # 10秒超时
                alerts = self.session.pop_alerts()
                for alert in alerts:
                    if isinstance(alert, lt.read_piece_alert) and alert.piece == piece_index:
                        piece_path = os.path.join(self.pieces_folder, f"piece_{piece_index}.dat")
                        with open(piece_path, "wb") as f:
                            f.write(alert.buffer)
                        return piece_path
                await asyncio.sleep(0.1)
            raise TimeoutError(f"Timeout waiting for piece {piece_index}")
        except Exception as e:
            print(f"Error saving piece {piece_index}: {e}")
            return None

    async def download(self):
        print(f'Current Date and Time (UTC): {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}')
        
        login(token=self.huggingface_token)

        try:
            repo_url = self.api.create_repo(
                repo_id=f"{self.USERNAME}/{self.REPO_NAME}",
                repo_type=self.REPO_TYPE,
                private=False
            )
        except Exception as e:
            print(f'Repository note: {e}')

        progress_data = self.load_progress_from_hf()
        
        handle = lt.add_magnet_uri(self.session, self.magnet_link, {
            'save_path': self.save_path,
            'storage_mode': lt.storage_mode_t.storage_mode_sparse
        })
        
        print('Getting metadata...')
        while not handle.has_metadata():
            await asyncio.sleep(1)

        print('Starting download...')
        torrent_info = handle.get_torrent_info()
        
        last_uploaded_piece = -1
        if progress_data:
            print("Resuming download...")
            last_uploaded_piece = progress_data['last_uploaded_piece']
            for piece in progress_data['downloaded_pieces']:
                handle.piece_priority(piece, 0)

        last_upload_time = time.time()
        last_status_update = time.time()
        
        print(f"Total size: {format_size(torrent_info.total_size())}")
        print(f"Piece length: {format_size(torrent_info.piece_length())}")
        print(f"Number of pieces: {torrent_info.num_pieces()}")

        while handle.status().state != lt.torrent_status.seeding:
            s = handle.status()
            current_time = time.time()
            
            if current_time - last_status_update >= self.STATUS_UPDATE_INTERVAL:
                self.update_download_status(handle, last_uploaded_piece)
                last_status_update = current_time
            
            if current_time - last_upload_time >= self.UPLOAD_INTERVAL:
                current_piece = int(s.progress * torrent_info.num_pieces())
                
                if current_piece > last_uploaded_piece:
                    print(f"\nUploading pieces {last_uploaded_piece + 1} to {current_piece}...")
                    for piece_index in range(last_uploaded_piece + 1, current_piece + 1):
                        if handle.have_piece(piece_index):
                            piece_path = await self.save_piece(handle, piece_index)
                            if piece_path:
                                try:
                                    self.api.upload_file(
                                        path_or_fileobj=piece_path,
                                        path_in_repo=f"pieces/piece_{piece_index}.dat",
                                        repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                                        repo_type=self.REPO_TYPE
                                    )
                                    os.remove(piece_path)
                                    print(f"Uploaded piece {piece_index}")
                                except Exception as e:
                                    print(f"Error uploading piece {piece_index}: {e}")
                    
                    last_uploaded_piece = current_piece
                    self.save_progress_to_hf(handle, last_uploaded_piece)
                
                last_upload_time = current_time
            
            await asyncio.sleep(1)

        print('Download Complete!')
        self.save_progress_to_hf(handle, torrent_info.num_pieces() - 1)

async def start_download(magnet_link, save_path, huggingface_token):
    downloader = TorrentDownloader(magnet_link, save_path, huggingface_token)
    await downloader.download()

if __name__ == "__main__":
    magnet_link = "magnet:?xt=urn:btih:8123f386aa6a45e26161753a3c0778f8b9b4d4cb&dn=Totoro_FTR-4_F_EN-en-CCAP_US-G_51_2K_GKID_20230303_GKD_IOP_OV&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&tr=udp%3A%2F%2Fexodus.desync.com%3A6969%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce"
    save_path = "Torrent/"
    huggingface_token = sys.argv[1]
    asyncio.run(start_download(magnet_link, save_path, huggingface_token))