import threading
import asyncio
import os
# Import the main functions from your two bot files
from concrete_logistics_bot import main as main1
from bot import main as main2

def run_bot1():
    # Runs the Logistics Bot
    asyncio.run(main1())

def run_bot2():
    # Runs the PI Bot
    asyncio.run(main2())

if __name__ == "__main__":
    t1 = threading.Thread(target=run_bot1)
    t2 = threading.Thread(target=run_bot2)

    t1.start()
    t2.start()

    t1.join()
    t2.join()
