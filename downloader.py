import asyncio

class DownloadManager:
    def __init__(self):
        self.downloads = []

    def get_download_data(self):
        return self.downloads

    async def download_files(self):
        while True:
            for download in self.downloads:
                # Update download progress and speed here
                download["downloaded"] += 10
                download["speed"] = 10
                if download["downloaded"] >= download["size"]:
                    download["downloaded"] = download["size"]
                    download["speed"] = 0
            await asyncio.sleep(1)

download_manager = DownloadManager()

async def main():
    asyncio.create_task(download_manager.download_files())
    # Keep the event loop running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())