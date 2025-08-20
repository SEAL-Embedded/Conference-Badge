import bluetooth
import aioble
import asyncio
import struct
from machine import Pin
from utime import sleep


_BADGE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")
_INFO_CHAR_UUID = bluetooth.UUID("aa01b013-dcea-4880-9d89-a47e76c69c3c")
_MATCH_CHAR_UUID = bluetooth.UUID("2aca7f5b-02b7-4232-a5f0-56cb9155be7a")

# How frequently to send advertising beacons.
_ADV_INTERVAL_MS = 250_000

#get the LED
pin = Pin("LED", Pin.OUT)

''' legend for the "roles" (?):
degree = o if hs
degree = 1 if undergrad
degree = 2 if graduate'''


#these can only do numbers for now:
def encode(temp):
    return struct.pack("<h", int(temp * 100))

def _decode(message):
    return struct.unpack("<h", message)[0] / 100 


class Badge:
    def __init__(self, major, degree):
        #set info attributes
        self.set_major = major
        self.set_degree = degree

        #set and registed service and characteristics
        self.badge_service = aioble.Service(_BADGE_UUID)
        self.info_characteristic = aioble.Characteristic(
            self.badge_service, _INFO_CHAR_UUID, read=True, notify=True
        )
        self.match_characteristic = aioble.Characteristic(
            self.badge_service, _MATCH_CHAR_UUID, read=True, write=True, notify=True
        )
        aioble.register_services(self.badge_service)

    #set the info in the characteristic:
    async def setup_task(self):
        await asyncio.sleep_ms(1000)
        self.info_characteristic.write(encode(self.set_degree), send_update=True)
        print(self.set_degree)
        await asyncio.sleep_ms(1000)
        self.info_characteristic.write(encode(self.set_major), send_update=True)
        print(self.set_major)

    #scanning method
    async def find_other(self):
        async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
            async for result in scanner:
                if _BADGE_UUID in result.services():
                    print(f"Found device: {result.device}")
                    print(f"Services advertised: {result.services()}")  # Debug line
                    return result.device
        return None

    #advertises all the time excluding the connection 
    async def advertise(self):
        while True:
            #this block starts advertising and continues ONLY WHEN the connection is established
            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name="WHY IS THIS NOT DISPLAYING",
                services=[_BADGE_UUID],
                appearance=0,
            ) as connection:
                #word "connection" is just a way of naming whatever this function returns
                print("Connection from", connection.device)
                self.connected_device = connection.device
                await connection.disconnected(timeout_ms=None)

    #reads the info + gives feedback, uses the device from find_other method
    async def evaluate_connection(self):

        device = await self.find_other()
        if not device:
            if self.connected_device:
                device = self.connected_device
            else:
                print("Device not found")
                return
        
        #connecting
        try:
            print("Connecting to", device)
            connection = await device.connect()
        except asyncio.TimeoutError:
            print("Timeout during connection")
            return
        
        #when connected - get access to server and characteristic 
        async with connection:
            try:
                self.badge_connection_service = await connection.service(_BADGE_UUID)

                if self.badge_connection_service is None:
                    print("Service not found!")
                    return
                
                self.info_connection_characteristic = await self.badge_connection_service.characteristic(_INFO_CHAR_UUID)
                print("Characteristic found successfully")
                self.match_connection_characteristic = await self.badge_connection_service.characteristic(_MATCH_CHAR_UUID)

            except asyncio.TimeoutError:
                print("Timeout discovering services/characteristics")
                return
            
            #when connected, read and decode
            if connection.is_connected():
                degree = await self.info_connection_characteristic.read()
                degree = _decode(degree)
                print("Degree: ", degree)
                await asyncio.sleep_ms(1000)

                major = await self.info_connection_characteristic.read()
                major = _decode(major)
                print("Planned Degree: ", major)
                await asyncio.sleep_ms(1000)

                if self.check_match(degree, major):
                    #the writing needs to be changed
                    self.match_connection_characteristic.write(encode(self.check_match(degree, major)))
                    pin.on()
                    sleep(1) # sleep 1sec
                    pin.off()
                    print("Finished.")

    def check_match(self, degree, major):
        match = 0
        if degree == self.set_degree:
            match += 1
        if major == self.set_major:
            match += 1

        if match == 2:
            print("Good match!")
            return True
        else:
            print("Bad match")
            return False
    
    async def run_task(self):
        await self.setup_task()
        advertise = asyncio.create_task(self.advertise())
        await self.evaluate_connection()
        
        #does advertising forever
        await advertise

async def main():
    badge = Badge(0, 0)
    await badge.run_task()

asyncio.run(main())
