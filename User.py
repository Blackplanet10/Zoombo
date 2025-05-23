# User.py
import JSONMutex
import asyncio

async def generate_id():
    server_settings = JSONMutex.JSONMutex("settings/server_settings.json")
    data = await server_settings.read_json()
    new_data = data
    new_data["LAST_ID"] = data["LAST_ID"] + 1
    await server_settings.write_json(new_data)
    return new_data["LAST_ID"]

class User:
    def __init__(self, name):
        self.name = name
        self.id = asyncio.run(generate_id())
