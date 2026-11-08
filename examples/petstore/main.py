"""Petstore API demo - shows basic CRUD operations with async middleware."""

import asyncio
import logging
import random
import time

import httpx
from client import AsyncClient, AsyncHandlerT
from client.models import Category, Pet, Tag

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("petstore")


async def main() -> None:
    print("🐶 Initializing Petstore Client...")

    client = AsyncClient(base_url="https://petstore3.swagger.io/api/v3")

    # Middleware: Log requests with timing
    @client.middleware
    async def log_requests(
        request: httpx.Request, call_next: AsyncHandlerT
    ) -> httpx.Response:
        logger.info(f"--> {request.method} {request.url}")
        start = time.time()
        response = await call_next(request)
        logger.info(f"<-- {response.status_code} ({time.time() - start:.3f}s)")
        return response

    # Middleware: Retry on server errors
    @client.middleware
    async def retry_on_error(
        request: httpx.Request, call_next: AsyncHandlerT
    ) -> httpx.Response:
        response = await call_next(request)
        for attempt in range(2):
            if response.status_code not in {429, 500, 502, 503}:
                break
            await asyncio.sleep(2**attempt + random.uniform(0, 0.1))
            response = await call_next(request)
        return response

    # 1. Find available pets
    print("\n--- 1. Find Available Pets ---")
    found = await client.GET("/pet/findByStatus", status="available")
    if found.data is not None:
        print(f"✅ Found {len(found.data)} pets")
        if found.data:
            sample = found.data[0]
            print(f"   Sample: {sample['name']} (ID: {sample.get('id')})")
    else:
        print(f"❌ Failed: {found.error}")

    # 2. Create a new pet
    print("\n--- 2. Create a Pet ---")
    pet_id = int(time.time())
    new_pet = Pet(
        id=pet_id,
        name="Fluffy",
        category=Category(id=1, name="Dogs"),
        photoUrls=["https://example.com/dog.jpg"],
        tags=[Tag(id=1, name="generated")],
        status="available",
    )
    created = await client.POST("/pet", json=new_pet)
    if created.data is not None:
        print(f"✅ Created: {created.data['name']} (ID: {created.data.get('id')})")
    else:
        print(f"❌ Failed: {created.error}")
        return

    # 3. Get the pet by ID — unwrap() raises ResponseError on failure
    print(f"\n--- 3. Get Pet {pet_id} ---")
    pet = (await client.GET("/pet/{pet_id}", pet_id=pet_id)).unwrap()
    print(f"✅ Retrieved: {pet['name']}")

    # 4. Delete the pet
    print(f"\n--- 4. Delete Pet {pet_id} ---")
    deleted = await client.DELETE("/pet/{pet_id}", pet_id=pet_id)
    if deleted.is_success:
        print("✅ Deleted")
    else:
        print(f"❌ Failed: {deleted.error}")


if __name__ == "__main__":
    asyncio.run(main())
