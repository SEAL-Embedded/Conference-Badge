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

def _decode(message):
    return struct.unpack("<h", message)[0] / 100

''' 
legend for the "roles" (?):
degree = o if hs
degree = 1 if undergrad
degree = 2 if graduate

major = 0 if EE
major = 1 if CS
etc
'''

#set the degree in the set up I guess
degree = 0
major = 0

def encode(temp):
    return struct.pack("<h", int(temp * 100))

async def sensor_task():
    degree = 0
    await asyncio.sleep_ms(1000)
    temp_characteristic.write(encode(degree), send_update=True)
    print(degree)
    await asyncio.sleep_ms(1000)
    temp_characteristic.write(encode(major), send_update=True)
    print(major)

# Serially wait for connections. Don't advertise while a central is
# connected.
async def peripheral_task():
    while True:
        async with await aioble.advertise(
            _ADV_INTERVAL_MS,
            name="Pico 1",
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
