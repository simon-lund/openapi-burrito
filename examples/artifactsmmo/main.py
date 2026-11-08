"""Artifacts MMO API demo - shows public and authenticated endpoints."""

import asyncio
import os

import httpx
from client import AsyncClient, AsyncHandlerT


async def main() -> None:
    print("⚔️ Initializing Artifacts MMO Client...")

    client = AsyncClient(base_url="https://api.artifactsmmo.com")

    # Add auth middleware if token is available
    token = os.environ.get("ARTIFACTS_TOKEN")
    if token:

        @client.middleware
        async def auth(
            request: httpx.Request, call_next: AsyncHandlerT
        ) -> httpx.Response:
            request.headers["Authorization"] = f"Bearer {token}"
            return await call_next(request)

    # 1. Server status (public)
    print("\n--- 1. Server Status ---")
    status = await client.GET("/")
    if status.data is not None:
        server = status.data["data"]
        print(
            f"✅ Version: {server['version']} | "
            f"Online: {server['characters_online']} players"
        )
    else:
        print(f"❌ Failed: {status.error}")

    # 2. List items (public)
    print("\n--- 2. List Items ---")
    items = await client.GET("/items", page=1, size=5)
    if items.data is not None:
        print(f"✅ Found {items.data.get('total', '?')} items")
        for item in items.data["data"][:5]:
            print(f"   - {item['name']} ({item['code']})")
    else:
        print(f"❌ Failed: {items.error}")

    # 3. My characters (requires auth)
    if not token:
        print("\n⚠️ Set ARTIFACTS_TOKEN to access authenticated endpoints")
        return

    print("\n--- 3. My Characters ---")
    characters = await client.GET("/my/characters")
    if characters.data is not None:
        print(f"✅ Found {len(characters.data['data'])} characters")
        for character in characters.data["data"]:
            print(f"   - {character['name']} (Level {character['level']})")
    else:
        print(f"❌ Failed: {characters.error}")


if __name__ == "__main__":
    asyncio.run(main())
