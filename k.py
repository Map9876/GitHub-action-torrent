import libtorrent as lt
import time
import os
import sys
import json
from huggingface_hub import HfApi, login
from datetime import datetime

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

class TorrentDownloader:
    def __init__(self, magnet_link, save_path, huggingface_token, download_manager):
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
        self.download_manager = download_manager
        
        os.makedirs(self.pieces_folder, exist_ok=True)

    def load_progress_from_hf(self):
        """从HuggingFace加载进度"""
        try:
            # 尝试从HuggingFace下载进度文件
            progress_content = self.api.download_file(
                repo_id=f"{self.USERNAME}/{self.REPO_NAME}",
                filename="download_progress.json"
            )
            return json.loads(progress_content)
        except Exception as e:
            print(f"No previous progress found on HuggingFace: {e}")
            return None

    def save_progress_to_hf(self, handle, last_uploaded_piece):
        """保存进度到HuggingFace"""
        progress_data = {
            "last_uploaded_piece": last_uploaded_piece,
            "downloaded_pieces": [i for i in range(handle.get_torrent_info().num_pieces()) 
                                if handle.have_piece(i)],
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "total_pieces": handle.get_torrent_info().num_pieces()
        }
        
        # 保存到本地文件
        with open(self.progress_file, 'w') as f:
            json.dump(progress_data, f)
        
        # 上传到HuggingFace
        self.api.upload_file(
            path_or_fileobj=self.progress_file,
            path_in_repo="download_progress.json",
            repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
            repo_type=self.REPO_TYPE
        )
        return progress_data

    def resume_download(self, handle, progress_data):
        """根据进度恢复下载"""
        if not progress_data:
            return -1

        print(f"Resuming download from piece {progress_data['last_uploaded_piece'] + 1}")
        print(f"Previously downloaded {len(progress_data['downloaded_pieces'])} of {progress_data['total_pieces']} pieces")
        
        # 设置已经上传的数据块为已完成
        for piece in range(progress_data['last_uploaded_piece'] + 1):
            if piece in progress_data['downloaded_pieces']:
                handle.piece_priority(piece, 0)  # 已上传的部分不再下载
            else:
                handle.piece_priority(piece, 7)  # 未完成的部分设置高优先级

        return progress_data['last_uploaded_piece']

    def download(self):
        print(f'Current Date and Time (UTC): {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}')
        print(f"Username: {self.USERNAME}")
        
        login(token=self.huggingface_token)

        # 加载之前的进度
        progress_data = self.load_progress_from_hf()
        
        handle = lt.add_magnet_uri(self.session, self.magnet_link, {
            'save_path': self.save_path,
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
        })
        
        handle.set_sequential_download(1)
        self.session.start_dht()

        print('Downloading Metadata...')
        while not handle.has_metadata():
            time.sleep(1)

        print('Got Metadata, checking previous progress...')
        last_uploaded_piece = self.resume_download(handle, progress_data)
        
        torrent_info = handle.get_torrent_info()
        print(f"Total pieces: {torrent_info.num_pieces()}")
        print(f"Piece length: {format_size(torrent_info.piece_length())}")
        print(f"Total size: {format_size(torrent_info.total_size())}")
        
        last_upload_time = time.time()
        last_progress_save_time = time.time()
        
        while handle.status().state != lt.torrent_status.seeding:
            s = handle.status()
            current_time = time.time()
            if current_time - last_status_update >= 1:  # 每秒更新一次UI
                self.update_download_status(handle, last_uploaded_piece)
                last_status_update = current_time
            # 每5小时上传一次数据块
            if current_time - last_upload_time >= self.UPLOAD_INTERVAL:

                current_piece = int(s.progress * torrent_info.num_pieces())
                
                if current_piece > last_uploaded_piece:
                    print("\nSaving and uploading new pieces...")
                    for piece_index in range(last_uploaded_piece + 1, current_piece + 1):
                        if handle.have_piece(piece_index):
                            try:
                                # 读取并保存数据块
                                handle.read_piece(piece_index)
                                for alert in self.session.pop_alerts():
                                    if isinstance(alert, lt.read_piece_alert) and alert.piece == piece_index:
                                        piece_path = os.path.join(self.pieces_folder, f"piece_{piece_index}.dat")
                                        with open(piece_path, "wb") as f:
                                            f.write(alert.buffer)
                                        
                                        # 上传到HuggingFace
                                        self.api.upload_file(
                                            path_or_fileobj=piece_path,
                                            path_in_repo=f"pieces/piece_{piece_index}.dat",
                                            repo_id=f'{self.USERNAME}/{self.REPO_NAME}',
                                            repo_type=self.REPO_TYPE
                                        )
                                        os.remove(piece_path)
                                        print(f"Uploaded piece {piece_index}")
                            except Exception as e:
                                print(f"Error processing piece {piece_index}: {e}")
                    
                    last_uploaded_piece = current_piece
                    # 保存进度
                    self.save_progress_to_hf(handle, last_uploaded_piece)
                last_upload_time = current_time
            
            # 每5秒显示一次进度
            if current_time - last_progress_save_time >= 5:
                print(
                    f'Progress: {s.progress * 100:.2f}% | '
                    f'Speed: {format_size(s.download_rate)}/s | '
                    f'Pieces: {s.num_pieces}/{torrent_info.num_pieces()} | '
                    f'Last uploaded: {last_uploaded_piece} | '
                    f'Peers: {s.num_peers}'
                )
                last_progress_save_time = current_time
            
            time.sleep(1)

        print('Download Complete!')

if __name__ == "__main__":
    magnet_link = "magnet:?xt=urn:btih:8123f386aa6a45e26161753a3c0778f8b9b4d4cb&dn=Totoro_FTR-4_F_EN-en-CCAP_US-G_51_2K_GKID_20230303_GKD_IOP_OV&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&tr=udp%3A%2F%2Fexodus.desync.com%3A6969%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce"
    save_path = "Torrent/"
    huggingface_token = sys.argv[1]
    downloader = TorrentDownloader(magnet_link, save_path, huggingface_token)
    downloader.download()