import asyncio

async def my_gen():
    try:
        await asyncio.sleep(5)
        yield 1
    except asyncio.CancelledError:
        print("Generator was cancelled")
        raise

async def main():
    iterator = my_gen().__aiter__()
    try:
        await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
    except TimeoutError:
        print("Caught timeout!")
    
    try:
        await iterator.__anext__()
    except StopAsyncIteration:
        print("StopAsyncIteration raised on second attempt!")
    except Exception as e:
        print(f"Other exception: {type(e)}")

asyncio.run(main())
