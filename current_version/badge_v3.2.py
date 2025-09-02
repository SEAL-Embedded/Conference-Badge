# This function, given a raspberry pi pico W, connects to another raspberry pi pico W
# and lights up an LED depending on how close the other is. 

from machine import Pin
from utime import sleep, ticks_ms
import bluetooth
import aioble
import asyncio
import struct
import time

_BADGE_SERVICE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")
_INFO_CHAR_UUID = bluetooth.UUID("aa01b013-dcea-4880-9d89-a47e76c69c3c")
_MATCH_CHAR_UUID = bluetooth.UUID("2aca7f5b-02b7-4232-a5f0-56cb9155be7a")

# How frequently to send advertising beacons.
_ADV_INTERVAL_MS = 250_000

#get the LED
led = Pin("LED", Pin.OUT)
led1 = Pin(15, Pin.OUT)   
led2 = Pin(14, Pin.OUT)
switch = Pin(13, Pin.IN, Pin.PULL_DOWN)  # GP14 connected to switch

''' legend for the "roles" (?):
degree = o if hs
degree = 1 if undergrad
degree = 2 if graduate'''


def encode_info(info_list):
    # Pack multiple values into one message
    format_str = "<" + "h" * len(info_list)
    return struct.pack(format_str, *[int(x) for x in info_list])

def decode_info(message):
    # Unpack multiple values from message
    num_fields = len(message) // 2  # Each 'h' is 2 bytes
    format_str = "<" + "h" * num_fields
    return list(struct.unpack(format_str, message))

class ProximityTracker:
    def __init__(self, target_device, initial_rssi):
        self.target_device = target_device
        self.current_rssi = initial_rssi
        self.is_tracking = True
        self.last_seen = ticks_ms()
        self.connection = None
        
    def update_rssi(self, rssi):
        self.current_rssi = rssi
        self.last_seen = ticks_ms()

    def get_distance_status(self):
        #Distance = 10^((Measured Power - Instant RSSI)/(10*N))
        distance = 10**(-(-59 - self.current_rssi)/(10*2.5))
        return str(distance)
    
    def should_disconnect(self):
        # Disconnect if RSSI is very strong (< 1 meter) or haven't seen in 30 seconds
        time_since_seen = ticks_ms() - self.last_seen
        return self.current_rssi > -50 or time_since_seen > 30000

class Badge:
    def __init__(self, info_array, badgename, name=None):
        #set info attributes
        self.info = info_array
        '''self.set_major = info_array[0] #if len(info_array) > 0 else 0
        self.set_degree = info_array[1] #if len(info_array) > 1 else 0
        self.set_uni = info_array[2] #if len(info_array) > 2 else 0 '''
        
        #self.set_name = name
        self.set_badgename = badgename
        self.name = name 
        #set a dictionary to store active devices
        self.active_trackers = {}
        self.is_scanning = False

        self.already_connected = set()

        #some error handling:
        self.result_of_search = None
        self.device_addr_adv = None
        self.device_addr_scan = None
        #set and registed service and characteristics
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
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
        information = encode_info(self.info)
        self.info_characteristic.write(information, send_update=True)
        print(f"Badge {self.set_badgename} is set up.")
        await asyncio.sleep_ms(1000)

    #scanning method
    async def find_other(self):
        async with aioble.scan(5000, interval_us=30000, window_us=20000, active=True) as scanner:
            async for result in scanner:
                if _BADGE_SERVICE_UUID in result.services():
                    self.device_addr_scan = str(result.device) #hereeeeeeeeeee
                    current_rssi = result.rssi
                    print(f"Found device: {result.name()} RSSI: {result.rssi}")
                    if self.device_addr_scan in self.already_connected:
                        continue
                    else:
                        self.already_connected.add(self.device_addr_scan)
                        return result.device
        return None

    #advertises all the time excluding the connection 
    async def advertise(self):
        while True:
            #this block starts advertising and continues ONLY WHEN the connection is established
            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=self.set_badgename,
                services=[_BADGE_SERVICE_UUID],
                appearance=0,
            ) as connection:
                #word "connection" is just a way of naming whatever this function returns
                print("Advertising found connection!, from:", connection.device)
                self.device_addr_adv = str(connection.device)
                self.result_of_search = await self.evaluate_connection(connection)
#get the device address from the first connection and then update the rssi with a separate(!) scanning funciton
#store the connected addresses in the already_connected set, pull one you are working with rn to a changing variable 
#then: each scanning gives one rssi and returns nothing until the rssi is good enough, this should probably be ran 
#as shown in the example code in the notes

                await connection.disconnected(timeout_ms=None)
    
    def get_address(self):
        addr_scan = self.device_addr_scan
        addr_adv = self.device_addr_adv
        if addr_scan == None:
            return str(addr_adv)
        else: #error hereeeeeeeeeeee
            return str(addr_scan)

    #reads the info + gives feedback, uses the device from find_other method
    async def get_connection(self):

        device = await self.find_other()
        if not device:
            print("Device from find_other() was not found")
            return
        
        #connecting
        try:
            if device:
                print("Connecting to device from find_other!")
                connection = await device.connect()
                return connection                      
            else:
                print("Connection not found")
                return
            
        except asyncio.TimeoutError:
            print("Timeout during connection")
            return
            
    async def evaluate_connection(self, connection):

        

        

        try:
            self.badge_connection_service = await connection.service(_BADGE_SERVICE_UUID)

            if self.badge_connection_service is None:
                print("Service not found!")
                return False
                
            self.info_connection_characteristic = await self.badge_connection_service.characteristic(_INFO_CHAR_UUID)
            print("Characteristic found successfully")
            self.match_connection_characteristic = await self.badge_connection_service.characteristic(_MATCH_CHAR_UUID)

        except asyncio.TimeoutError:
            print("Timeout discovering services/characteristics")
            return False
            
        try:
            #when connected, read and decode
            read_info = await self.info_connection_characteristic.read()
            read_info = decode_info(read_info)
            print("Information: ", read_info)
            await asyncio.sleep_ms(1000)

            if self.check_match(read_info) == 1:
                #this writing is never used
                self.match_connection_characteristic.write()
                led.on()
                sleep(1) # sleep 1sec
                led.off()
                print("Finished evaluating connection.")

            #think about it...
            await asyncio.sleep_ms(200)
            await connection.disconnect()
            print("Disconnected from device")
            print()

            return True

        except Exception as e:
            print(f"Unknown exception: {e}")
            try:
                await connection.disconnect()
            except:
                pass  # Ignore disconnection errors
            return False

    def check_match(self, read_info):
        match = 0
        if read_info[0] == self.info[0]:
            match += 1
        if read_info[1] == self.info[1]:
            match += 1
        if read_info[2] == self.info[2]:
            match += 1

        if match >= 2:
            print("Good match!")
            #Set GP15 as output pin
            #led = Pin(15, Pin.OUT)
            #led.value(10)   # LED on
            time.sleep(1)  # wait 1 second
            return 1
        else:
            print("Bad match")
            return 0


    def humanize_rssi(self, rssi):
        if rssi > -50:
            print("Very close (< 1m)")
            return 1
        elif rssi > -65:
            print("Close (1-2m)")
            return 2
        elif rssi > -80:
            print("Getting closer (2-3m)")
            return 3
        elif rssi > -95:
            print("Medium distance (3-8m)")
            return 4
        else:
            print("Far away (> 8m)")
            return 5

    async def get_distance_feedback(self, rssi):
#-------------------------- based on the rssi, light up different colors: for 2-3 meters red/green, for 4-6 meters yellow, 
#-------------------------- for 7-10 meters green/red, for > 11 blue
        if self.humanize_rssi(rssi) == 1:
            #something like flashing green
            led1.value(1)
            await asyncio.sleep_ms(200)
            led1.value(0)

        elif self.humanize_rssi(rssi) == 2:
            #something like long green
            led2.value(1)
            await asyncio.sleep_ms(200)
            led2.value(0)

        elif self.humanize_rssi(rssi) == 3:
            #something like a flashing yellow
            led1.value(1)
            await asyncio.sleep_ms(200)
            led1.value(0)

        elif self.humanize_rssi(rssi) == 4:
            #something like a solid yellow
            led1.value(1)
            await asyncio.sleep_ms(200)
            led1.value(0)

        elif self.humanize_rssi(rssi) == 5:
            #something like a solid red, maybe actually if detects then maybe flashing red, otherwise - solid.
            led2.value(1)
            await asyncio.sleep_ms(200)
            led2.value(0)
        
            
    async def search_with_scan(self, addr, target_rssi, timeout_s):
        
        print("Starting to track")
        start_time = time.time()
        print(f"Scanning for device proximity (target RSSI: {target_rssi})")
    
        while (time.time() - start_time) < timeout_s:
            try:
                async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
                    async for result in scanner:
                        if str(result.device) == str(addr):
                            current_rssi = result.rssi
                            print(f"Found targeted device! RSSI: {result.rssi}")
                            
                            if current_rssi > target_rssi:
                                print("Target reached!")
#------------------------------ add a cool flash from LED to celebrate maybe?
                                return True
                            
                            print(f"Humanized rssi: {self.humanize_rssi(current_rssi)}m")
                            #moved into a separate function:
                            
                            await self.get_distance_feedback(current_rssi) 
                            
                            break
                await asyncio.sleep_ms(1000)  # Wait between scan cycles
            
            except Exception as e:
                print(f"Error during proximity scanning: {e}")
                await asyncio.sleep_ms(2000)

        print("Proxiscanning timeout :(")
        return False         

    async def run_task(self):
        await self.setup_task()
        advertise = asyncio.create_task(self.advertise())
        while True:
            
            await asyncio.sleep_ms(200)
            if not switch.value():  
                print("Switch off, skipping scan")
                #this should be ran on demand!!!
        #------ make a loop that will run util the power is turned off, add a condition of when the switch is turned on, then run the following:
                connection = await self.get_connection()
                if connection:
                    self.result_of_search = await self.evaluate_connection(connection)
                await asyncio.sleep_ms(5000)
                addr = self.get_address()
                print(str(addr))
                
                #ERROR IS HERE!!! Below! Just changed this:

                #if self.result_of_search:
                #    await self.search_with_scan(addr, -45, 20)
                
                await asyncio.sleep_ms(5000)
                await self.search_with_scan(addr, -45, 20)
                #lets do it again:
                led.on  
                sleep(1)  
                led.off
                await asyncio.sleep_ms(200)
                await self.search_with_scan(addr, -45, 20)
                #this is the end of the loop^

                #does advertising forever
        await advertise

async def main():
    badge = Badge([1, 2, 0], "AAAAA")
    await badge.run_task()

asyncio.run(main())
