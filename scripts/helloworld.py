import os
import sys
from datetime import datetime

def main():
    os.makedirs("/data", exist_ok=True)
    
    # Format name based on current time
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    file_path = f"/data/{timestamp}.txt"
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("helloworld")
    
    # 1. Output multiple lines to stdout
    print("helloworld")
    print(f"现在是 {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("这是脚本print的内容")
    
    # 2. Output to stderr
    print("WARNING: This is a simulated warning output in stderr.", file=sys.stderr)
    print("ERROR: Database connection pool is low (simulated stderr output).", file=sys.stderr)

if __name__ == "__main__":
    main()
