import bluetooth
import aioble
import asyncio
from micropython import const
import struct


ble = bluetooth.BLE()
ble.active(True)

'''set these to any uuid'''
_ENV_SENSE_UUID = bluetooth.UUID(0x181A)
_ENV_SENSE_TEMP_UUID = bluetooth.UUID(0x2A6E)

# How frequently to send advertising beacons.
_ADV_INTERVAL_MS = 250_000

# Register GATT server.
temp_service = aioble.Service(_ENV_SENSE_UUID)
temp_characteristic = aioble.Characteristic(
    temp_service, _ENV_SENSE_TEMP_UUID, read=True, notify=True
)
aioble.register_services(temp_service)


def encode(temp):
    return struct.pack("<h", int(temp * 100))


async def sensor_task():
    t = 24
    count = 0
    while count < 6:
        temp_characteristic.write(encode(t), send_update=True)
        print(encode(t)) 
        await asyncio.sleep_ms(1000)
        t += 1
        count += 1


# Serially wait for connections. Don't advertise while a central is
# connected.
async def peripheral_task():
    while True:
        async with await aioble.advertise(
            _ADV_INTERVAL_MS,
            name="mpy-temp",
            services=[_ENV_SENSE_UUID],
            appearance=0,
        ) as connection:
            print("Connection from", connection.device)
            await connection.disconnected(timeout_ms=None)

# Run both tasks.
async def main():
    t1 = asyncio.create_task(sensor_task())
    t2 = asyncio.create_task(peripheral_task())
    await asyncio.gather(t1, t2)


asyncio.run(main())