#!/bin/bash
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
HUGGINGFACE_TOKEN=$1

# Start the Python server
python3 server.py $HUGGINGFACE_TOKEN &