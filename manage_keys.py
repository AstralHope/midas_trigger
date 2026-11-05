import os
import sys
import argparse
import hashlib
import secrets
import json

KEYS_PATH = "keys.json"

def load_keys():
    if not os.path.exists(KEYS_PATH):
        return {"keys": []}
    try:
        with open(KEYS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {"keys": []}
    except Exception as e:
        print(f"Error reading {KEYS_PATH}: {e}")
        return {"keys": []}

def save_keys(data):
    try:
        with open(KEYS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error writing to {KEYS_PATH}: {e}")

def create_key(client_name):
    data = load_keys()
    # Check if client already exists
    for entry in data.get("keys", []):
        if entry.get("client") == client_name:
            print(f"Error: Client '{client_name}' already exists.")
            sys.exit(1)
            
    # Generate secure random key (24 bytes -> 48 hex chars)
    raw_key = secrets.token_hex(24)
    # Compute SHA-256 hash
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    
    # Save entry
    data.setdefault("keys", []).append({
        "client": client_name,
        "hash": key_hash
    })
    save_keys(data)
    
    print("=" * 60)
    print(f"API Key created successfully for client: {client_name}")
    print(f"Raw API Key (Copy this now! It will not be shown again):")
    print(f"\n{raw_key}\n")
    print(f"SHA-256 Hash stored in keys.json:")
    print(f"{key_hash}")
    print("=" * 60)

def list_keys():
    data = load_keys()
    keys = data.get("keys", [])
    if not keys:
        print("No API Keys found.")
        return
        
    print(f"{'Client':<25} | {'SHA-256 Hash'}")
    print("-" * 60)
    for entry in keys:
        print(f"{entry.get('client', 'N/A'):<25} | {entry.get('hash', 'N/A')}")

def revoke_key(client_name):
    data = load_keys()
    keys = data.get("keys", [])
    new_keys = [entry for entry in keys if entry.get("client") != client_name]
    
    if len(keys) == len(new_keys):
        print(f"Error: Client '{client_name}' not found.")
        sys.exit(1)
        
    data["keys"] = new_keys
    save_keys(data)
    print(f"API Key for client '{client_name}' has been successfully revoked.")

def main():
    parser = argparse.ArgumentParser(description="API Key Management Tool")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")
    
    # Create parser
    create_parser = subparsers.add_parser("create", help="Create a new API key")
    create_parser.add_argument("--client", required=True, help="Client/application name")
    
    # List parser
    subparsers.add_parser("list", help="List all clients and their hashes")
    
    # Revoke parser
    revoke_parser = subparsers.add_parser("revoke", help="Revoke/delete an API key")
    revoke_parser.add_argument("--client", required=True, help="Client/application name to revoke")
    
    args = parser.parse_args()
    
    if args.command == "create":
        create_key(args.client)
    elif args.command == "list":
        list_keys()
    elif args.command == "revoke":
        revoke_key(args.client)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
