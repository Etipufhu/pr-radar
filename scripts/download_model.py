"""Download a Hugging Face model into the local cache (shows progress)."""

import sys

from huggingface_hub import snapshot_download

name = sys.argv[1]
path = snapshot_download(name, allow_patterns=["*.json", "*.safetensors", "*.txt", "LICENSE"])
print(f"done: {path}")
