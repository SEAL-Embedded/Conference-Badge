import bluetooth
import aioble
import asyncio
import struct
from machine import Pin
from utime import sleep

#ble = bluetooth.BLE()
#ble.active(True)

set_degree = 0
set_major = 0
pin = Pin("LED", Pin.OUT)

'''these are set in the server, here to compare the addresses'''
_ENV_SENSE_UUID = bluetooth.UUID(0x181A)
_ENV_SENSE_TEMP_UUID = bluetooth.UUID(0x2A6E)

async def find_other():
    async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
        async for result in scanner:
            # See if it matches our name and the environmental sensing service.
            if result.name() == "Pico 1" and _ENV_SENSE_UUID in result.services():
                return result.device
    return None

def _decode(message):
    return struct.unpack("<h", message)[0] / 100 

def check_match(degree, major):
    match = 0
    if degree == set_degree:
        match += 1
    elif major == set_major:
        match += 1

    if match < 2:
        print("Good match!")
        return True
    else:
        print("...")
        return False

async def main():
    device = await find_other()
    if not device:
        print("Temperature sensor not found")
        return

    try:
        print("Connecting to", device)
        connection = await device.connect()
    except asyncio.TimeoutError:
        print("Timeout during connection")
        return

    async with connection:
        try:
            temp_service = await connection.service(_ENV_SENSE_UUID)
            temp_characteristic = await temp_service.characteristic(_ENV_SENSE_TEMP_UUID)
        except asyncio.TimeoutError:
            print("Timeout discovering services/characteristics")
            return

        if connection.is_connected():
            degree = await temp_characteristic.read()
            degree = _decode(degree)
            print("Degree: ", degree)
            await asyncio.sleep_ms(1000)

            major = await temp_characteristic.read()
            major = _decode(major)
            print("Planned Degree: ", major)
            await asyncio.sleep_ms(1000)

            if check_match(degree, major):
                pin.on()
                sleep(1) # sleep 1sec
                pin.off()
                sleep(1)
                pin.on()
                sleep(1) # sleep 1sec
                pin.off()
                print("Finished.")

asyncio.run(main())
