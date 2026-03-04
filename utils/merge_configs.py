# merge_configs.py

import os

# Target list, consistent with SimpleSpider.targets
targets = (
    "clashmeta",
    "ndnode",
    "nodev2ray",
    "nodefree",
    "v2rayshare",
    "wenode",
)

# Config file directory
NODES_DIR = "nodes"
# Output file
OUTPUT_FILE = os.path.join(NODES_DIR, "simple.txt")

def merge_configs():
    """Merge all target txt config files into simple.txt"""
    merged_content = []
    
    for target in targets:
        file_path = os.path.join(NODES_DIR, f"{target}.txt")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
                if content:
                    merged_content.append(content)
    
    # Write merged content
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(merged_content))
    
    print(f"Successfully merged configs to {OUTPUT_FILE}")

if __name__ == "__main__":
    merge_configs()
