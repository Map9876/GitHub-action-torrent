document.addEventListener("DOMContentLoaded", () => {
    const downloadsContainer = document.getElementById("downloads");

    const updateDownloads = (downloads) => {
        downloadsContainer.innerHTML = '';
        downloads.forEach(download => {
            const fileElement = document.createElement("div");
            fileElement.innerHTML = `
                <h2>${download.path}</h2>
                <p>Size: ${download.size} bytes</p>
                <p>Downloaded: ${download.downloaded} bytes</p>
                <p>Speed: ${download.speed} kB/s</p>
                <progress value="${download.downloaded}" max="${download.size}"></progress>
            `;
            downloadsContainer.appendChild(fileElement);
        });
    };

    const ws = new WebSocket("ws://localhost:8765");
    ws.onmessage = (event) => {
        const downloads = JSON.parse(event.data);
        updateDownloads(downloads);
    };
});