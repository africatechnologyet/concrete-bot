import asyncio
from bot import main as start_pi_bot
from logistics_bot import main as start_logistics_bot

async def run():
    # This runs both bots at the same time without crashing
    await asyncio.gather(start_pi_bot(), start_logistics_bot())

if __name__ == '__main__':
    asyncio.run(run())
