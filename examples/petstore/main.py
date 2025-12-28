"""Petstore API demo - shows basic CRUD operations with middleware."""

import logging
import random
import time

from client import Client
from client.models import Category, Pet, Tag

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("petstore")


def main():
    print("🐶 Initializing Petstore Client...")

    client = Client(base_url="https://petstore3.swagger.io/api/v3")

    # Middleware: Log requests with timing
    @client.middleware
    def log_requests(request, call_next):
        logger.info(f"--> {request.method} {request.url}")
        start = time.time()
        response = call_next(request)
        logger.info(f"<-- {response.status_code} ({time.time() - start:.3f}s)")
        return response

    # Middleware: Retry on server errors
    @client.middleware
    def retry_on_error(request, call_next):
        for attempt in range(3):
            response = call_next(request)
            if response.status_code in [500, 502, 503, 429] and attempt < 2:
                time.sleep(2**attempt + random.uniform(0, 0.1))
                continue
            return response
        return response

    # 1. Find available pets
    print("\n--- 1. Find Available Pets ---")
    res = client.GET("/pet/findByStatus", status="available")
    if res.is_success:
        pets = res.data
        print(f"✅ Found {len(pets)} pets")
        if pets:
            print(f"   Sample: {pets[0]['name']} (ID: {pets[0]['id']})")
    else:
        print(f"❌ Failed: {res.error}")

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
    res = client.POST("/pet", json=new_pet)
    if res.is_success:
        print(f"✅ Created: {res.data['name']} (ID: {res.data['id']})")
    else:
        print(f"❌ Failed: {res.error}")
        return

    # 3. Get the pet by ID (path now uses snake_case: /pet/{pet_id})
    print(f"\n--- 3. Get Pet {pet_id} ---")
    res = client.GET("/pet/{pet_id}", pet_id=pet_id)
    if res.is_success:
        print(f"✅ Retrieved: {res.data['name']}")
    else:
        print(f"❌ Failed: {res.error}")

    # 4. Delete the pet
    print(f"\n--- 4. Delete Pet {pet_id} ---")
    res = client.DELETE("/pet/{pet_id}", pet_id=pet_id)
    if res.is_success:
        print("✅ Deleted")
    else:
        print(f"❌ Failed: {res.error}")


if __name__ == "__main__":
    main()
