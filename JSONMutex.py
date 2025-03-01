import json
import os
import fcntl  # For Unix-based systems
import asyncio
from contextlib import asynccontextmanager


class JSONMutex:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.lock_file = f"{file_path}.lock"

    @asynccontextmanager
    async def lock(self):
        """Async context manager for acquiring and releasing the file lock."""
        with open(self.lock_file, 'w') as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX)  # Acquire an exclusive lock
            try:
                yield  # Perform operations inside this block
            finally:
                fcntl.flock(lockfile, fcntl.LOCK_UN)  # Release the lock

    async def read_json(self):
        """Read the JSON file safely, retrying until data is available."""
        while True:
            async with self.lock():
                if os.path.exists(self.file_path):
                    with open(self.file_path, 'r') as f:
                        data = json.load(f)
                        if data:
                            return data
            await asyncio.sleep(1)  # Non-blocking wait before retrying

    async def write_json(self, data):
        """Write data to the JSON file safely, retrying until successful."""
        while True:
            try:
                async with self.lock():
                    with open(self.file_path, 'w') as f:
                        json.dump(data, f, indent=4)
                    return  # Exit once writing is successful
            except Exception as e:
                print(f"Write failed, retrying: {e}")
                await asyncio.sleep(1)  # Non-blocking wait before retrying


# Example usage
async def main():
    json_mutex = JSONMutex("data.json")

    # Writing safely with retries
    new_data = {"count": 1}
    await json_mutex.write_json(new_data)

    # Reading safely until data is available
    print(await json_mutex.read_json())


if __name__ == "__main__":
    asyncio.run(main())
