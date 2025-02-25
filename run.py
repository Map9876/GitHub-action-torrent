import libtorrent as lt
import time
import os
import hashlib
import sys
from huggingface_hub import HfApi

def print_file_hashes(torrent_info, save_path):
    print("Torrent files and their hashes:")
    for file_index in range(torrent_info.num_files()):
        file_entry = torrent_info.file_at(file_index)
        file_path = os.path.join(save_path, file_entry.path)
        print(f"File: {file_entry.path}")
        print(f"Expected Hash: {file_entry.sha1_hash}")
        if os.path.exists(file_path):
            local_hash = compute_file_hash(file_path)
            print(f"Local Hash: {local_hash}")
        else:
            print("Local file not found.")
        print()

def compute_file_hash(file_path):
    sha1 = hashlib.sha1()
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            sha1.update(chunk)
    return sha1.hexdigest()

def format_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

def print_progress(handle, files):
    s = handle.status()
    file_status = handle.file_status()
    
    # Move cursor to the beginning of the progress display
    print("\033[F" * (len(files) + 2))
    
    for i, file_info in enumerate(files):
        file_size = file_info["size"]
        downloaded = file_status[i].bytes_complete
        print(f"{file_info['path']} - {format_size(downloaded)} / {format_size(file_size)}")
    
    print(f"Total: {format_size(s.total_done)} / {format_size(s.total_wanted)}")
    print(f"Download: {s.download_rate / 1000:.1f} kB/s, Upload: {s.upload_rate / 1000:.1f} kB/s, Peers: {s.num_peers}")

def download_torrent_with_priority(magnet_link, save_path, huggingface_token):
    # 创建 HfApi 实例
    api = HfApi()

    # 提取用户名
    USERNAME = "servejjjhjj"
    print(f'Your username is: {USERNAME}')
    from huggingface_hub import login 
    login(token=huggingface_token)
    print("密钥")
    
    # 储存库的名称
    REPO_NAME = 'mp4-dataset'
    REPO_TYPE = 'dataset'  # 可以是 'model', 'dataset', 或 'space'

    # 创建储存库
    repo_url = api.create_repo(
        repo_id=f"{USERNAME}/{REPO_NAME}",
        repo_type=REPO_TYPE,
        private=False
    )

    print(f'Repository created: {repo_url}')

    ses = lt.session()
    params = {
        'save_path': save_path,
        'storage_mode': lt.storage_mode_t.storage_mode_sparse,
    }
    handle = lt.add_magnet_uri(ses, magnet_link, params)
    handle.set_sequential_download(1)
    ses.start_dht()

    print('Downloading Metadata...')
    while not handle.has_metadata():
        time.sleep(1)

    print('Got Metadata, Starting Torrent Download...')
    torrent_info = handle.get_torrent_info()
    
    files = sorted([
        {"index": i, "path": torrent_info.files().file_path(i), "size": torrent_info.files().file_size(i)}
        for i in range(torrent_info.num_files())
    ], key=lambda x: x["size"], reverse=True)

    # Print initial file list
    for file_info in files:
        print(f"{file_info['path']} - {format_size(file_info['size'])}")
    print()

    for file_info in files:
        # Set current file highest priority
        handle.file_priority(file_info["index"], 7)
        # Set other files to not download
        for other in files:
            if other["index"] != file_info["index"]:
                handle.file_priority(other["index"], 0)

        while handle.status().state != lt.torrent_status.seeding:
            print_progress(handle, files)
            time.sleep(5)
        
        # File downloaded, move to Hugging Face
        local_file_path = os.path.join(save_path, file_info["path"])
        if os.path.exists(local_file_path):
            print(f"Uploading {local_file_path} to Hugging Face...")
            api.upload_file(
                path_or_fileobj=local_file_path,
                path_in_repo=file_info["path"],
                repo_id=f'{USERNAME}/{REPO_NAME}',  # 使用获取的用户名
                repo_type=REPO_TYPE)
            print(f"Uploaded {local_file_path} to Hugging Face.")
            os.remove(local_file_path)
            print(f"Deleted local file {local_file_path}.")

    print('Download Complete')

# 示例调用
if __name__ == "__main__":
    magnet_link = "magnet:?xt=urn:btih:8123f386aa6a45e26161753a3c0778f8b9b4d4cb&dn=Totoro_FTR-4_F_EN-en-CCAP_US-G_51_2K_GKID_20230303_GKD_IOP_OV&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&tr=udp%3A%2F%2Fexodus.desync.com%3A6969%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce"
    save_path = "Torrent/"
    huggingface_token = sys.argv[1]
    download_torrent_with_priority(magnet_link, save_path, huggingface_token)
