import json
import os
import asyncio
from contextlib import asynccontextmanager

if os.name == 'posix':
    import fcntl
elif os.name == 'nt':
    import msvcrt

class JSONMutex:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.lock_file = f"{file_path}.lock"

    @asynccontextmanager
    async def lock(self):
        """Async context manager for acquiring and releasing the file lock."""
        with open(self.lock_file, 'w') as lockfile:
            if os.name == 'nt':
                # Ensure the file has at least one byte for locking.
                lockfile.write("0")
                lockfile.flush()
                # Lock 1 byte from the beginning of the file.
                msvcrt.locking(lockfile.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(lockfile, fcntl.LOCK_EX)
            try:
                yield  # Operations inside the lock.
            finally:
                if os.name == 'nt':
                    msvcrt.locking(lockfile.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lockfile, fcntl.LOCK_UN)

    async def read_json(self):
        """Read the JSON file safely, retrying until data is available."""
        while True:
            async with self.lock():
                if os.path.exists(self.file_path):
                    with open(self.file_path, 'r') as f:
                        try:
                            data = json.load(f)
                        except json.JSONDecodeError:
                            data = None
                        if data:
                            return data
            await asyncio.sleep(0.1)  # Non-blocking wait before retrying

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
                await asyncio.sleep(0.1)  # Non-blocking wait before retrying

# Example usage
async def main():
    json_mutex = JSONMutex("data.json")
    new_data = {"count": 1}
    await json_mutex.write_json(new_data)
    print(await json_mutex.read_json())

if __name__ == "__main__":
    asyncio.run(main())
