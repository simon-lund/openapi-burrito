"""Artifacts MMO API demo - shows public and authenticated endpoints."""

import os

from client import Client


def main():
    print("⚔️ Initializing Artifacts MMO Client...")

    client = Client(base_url="https://api.artifactsmmo.com")

    # Add auth middleware if token is available
    token = os.environ.get("ARTIFACTS_TOKEN")
    if token:
        @client.middleware
        def auth(request, call_next):
            request.headers["Authorization"] = f"Bearer {token}"
            return call_next(request)

    # 1. Server status (public)
    print("\n--- 1. Server Status ---")
    res = client.GET("/")
    if res.is_success:
        data = res.data.get("data", {})
        print(f"✅ Version: {data.get('version')} | Online: {data.get('characters_online')} players")
    else:
        print(f"❌ Failed: {res.error}")

    # 2. List items (public)
    print("\n--- 2. List Items ---")
    res = client.GET("/items", page=1, size=5)
    if res.is_success:
        items = res.data.get("data", [])
        print(f"✅ Found {res.data.get('total', '?')} items")
        for item in items[:5]:
            print(f"   - {item['name']} ({item['code']})")
    else:
        print(f"❌ Failed: {res.error}")

    # 3. My characters (requires auth)
    if not token:
        print("\n⚠️ Set ARTIFACTS_TOKEN to access authenticated endpoints")
        return

    print("\n--- 3. My Characters ---")
    res = client.GET("/my/characters")
    if res.is_success:
        chars = res.data.get("data", [])
        print(f"✅ Found {len(chars)} characters")
        for char in chars:
            print(f"   - {char['name']} (Level {char['level']})")
    else:
        print(f"❌ Failed: {res.error}")


if __name__ == "__main__":
    main()
