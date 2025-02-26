nj
n

# GitHub-action-torrent
https://github.com/Map9876/GitHub-action-torrent/blob/2f46e4c4cc869a5e75e867edbb0d7466e363092d/download_torrent.py

1
Failed to create repository servejjjhjj/mp4-dataset. Error: 409 Client Error: Conflict for url: https://huggingface.co/api/repos/create (Request ID: Root=1-67be1b33-6b85f35156f31f810c4683cd;70e5de64-e8c4-494e-af95-64375ad3fd2f)
22

23
You already created this dataset repo
24
Skipping repository creation and continuing...
25
Downloading Metadata...
26
Got Metadata, Starting Torrent Download...
27
Totoro_FTR-4_F_EN-en-CCAP_US-G_51_2K_GKID_20230303_GKD_IOP_OV/cd90c15a-d77f-48d1-b3b6-5455650ffccd_video.mxf - 15.80 GB
28
Totoro_FTR-4_F_EN-en-CCAP_US-G_51_2K_GKID_20230303_GKD_IOP_OV/b73b8ecd-60aa-469d
f5aac6d6fd1a_video.mxf - 2.14 GB
35
Traceback (most recent call last):
36
  File "/home/runner/work/GitHub-action-torrent/GitHub-action-torrent/./run.py", line 140, in <module>
37
    download_torrent_with_priority(magnet_link, save_path, huggingface_token)
38
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
39
  File "/home/runner/work/GitHub-action-torrent/GitHub-action-torrent/./run.py", line 117, in download_torrent_with_priority
40
    print_progress(handle, files)
41
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
42
  File "/home/runner/work/GitHub-action-torrent/GitHub-action-torrent/./run.py", line 48, in print_progress
43
    downloaded = file_status[i].bytes_complete
44
                 ~~~~~~~~~~~^^^
45
IndexError: list index out of range
46
Totoro_FTR-4_F_EN-en-CCAP_US-G_51_2K_GKID_20230303_GKD_IOP_OV/9389b9a1-6d53-4420-baeb-2448693a30de_audio.mxf - 1012.69 MB