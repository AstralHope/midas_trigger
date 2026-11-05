#!/bin/bash

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
FILE_PATH="/data/${TIMESTAMP}.txt"

echo "helloworld" > "$FILE_PATH"

echo "helloworld"
echo "现在是 $(date +"%Y-%m-%d %H:%M:%S")"
echo "这是 Shell 脚本 echo 的内容"

echo "WARN: This is a simulated warning from shell script." >&2
