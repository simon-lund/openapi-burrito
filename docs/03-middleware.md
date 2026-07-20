# Middleware

The generated client includes a middleware system for intercepting requests and
responses. This is useful for logging, authentication, retry logic, and custom
error handling.

> **Note**: This middleware pattern is inspired by
> [FastAPI middleware](https://fastapi.tiangolo.com/tutorial/middleware/).

## Basic Middleware

Middleware is a function that takes a `request` and a `call_next` function.
With the default `AsyncClient`, middleware is a coroutine function and
`call_next` must be awaited:

```python
from my_client import AsyncClient

client = AsyncClient(base_url="https://api.example.com")

@client.middleware
async def logging_middleware(request, call_next):
    print(f"→ {request.method} {request.url}")
    response = await call_next(request)
    print(f"← {response.status_code}")
    return response
```

> The sync `Client` (`--client sync`) works exactly the same — just drop the
> `async` and `await` keywords.

## Middleware with Timing

```python
import time

@client.middleware
async def timing_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    print(f"{request.method} {request.url} took {duration:.3f}s")
    return response
```

## Retry Middleware

```python
import asyncio
import random

@client.middleware
async def retry_middleware(request, call_next):
    max_retries = 3

    for attempt in range(max_retries + 1):
        response = await call_next(request)

        # Retry on server errors or rate limits
        if response.status_code in [500, 502, 503, 504, 429]:
            if attempt < max_retries:
                sleep_time = (2 ** attempt) + random.uniform(0, 0.1)
                await asyncio.sleep(sleep_time)
                continue

        return response

    return response
```

## Execution Order

Middlewares execute in an "onion" pattern — the first middleware added is the outermost layer.

```python
@client.middleware
async def outer(request, call_next):
    print("1. Before")
    response = await call_next(request)
    print("4. After")
    return response

@client.middleware
async def inner(request, call_next):
    print("2. Before")
    response = await call_next(request)
    print("3. After")
    return response
```

Output:
| Middleware Name  | Message          |
| ---------------- | ---------------- |
| outer            | 1. Before        |
| inner            | 2. Before        |
| (actual request) | (actual request) |
| inner            | 3. After         |
| outer            | 4. After         |

## Adding Middleware Programmatically

```python
async def my_middleware(request, call_next):
    # ...
    return await call_next(request)

client.add_middleware(my_middleware)
```
