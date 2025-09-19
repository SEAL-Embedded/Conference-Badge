

#switch version!

from machine import Pin
from utime import sleep
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
red = Pin(15, Pin.OUT)
green = Pin(14, Pin.OUT)
blue = Pin(13, Pin.OUT)
turnOn = Pin(12, Pin.OUT)

led = Pin("LED", Pin.OUT)

def led_off():
    red.value(1)
    green.value(1)
    blue.value(1)

def led_color(r, g, b):
    # Inverted logic for common anode
    red.value(0 if r else 1)
    green.value(0 if g else 1)
    blue.value(0 if b else 1)
    turnOn.value(3)

switch = Pin(11, Pin.IN, Pin.PULL_DOWN)  # GP11 connected to switch

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

class Badge:
    #this creates fields for the Badge object, including the name, info_array and service with characteristic
    def __init__(self, info_array, badgename, name=None):
        #set info attributes
        self.info = info_array
        '''self.set_major = info_array[0] #if len(info_array) > 0 else 0
        self.set_degree = info_array[1] #if len(info_array) > 1 else 0
        self.set_uni = info_array[2] #if len(info_array) > 2 else 0 '''
        
        #self.set_name = name
        self.set_badgename = badgename
        self.name = name 

        #set and registed service and characteristics
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        self.info_characteristic = aioble.Characteristic(self.badge_service, _INFO_CHAR_UUID, read=True, notify=True)
        self.match_characteristic = aioble.Characteristic(self.badge_service, _MATCH_CHAR_UUID, read=True, write=True)

        aioble.register_services(self.badge_service)

#------ this is very weird, for what?
        self.addr = None

        #event setup
        self.good_match = asyncio.Event()

#------ this set of already connected is not used currently 
        self.already_connected = set()
        
#------ this should be looked over 
        self.device_addr_adv = None
        self.device_addr_scan = None

    #first function called, set the info in the characteristic, waits 1 sec before and after
    async def setup_task(self):
        await asyncio.sleep_ms(1000)
        information = encode_info(self.info)
        self.info_characteristic.write(information, send_update=True)
        print(f"Badge {self.set_badgename} is set up.")
        await asyncio.sleep_ms(1000)

    #scans for the devices with the set service, returns the device object if found, otherwise - None
    async def find_other(self):
        async with aioble.scan(5000, interval_us=30000, window_us=20000, active=True) as scanner:
            async for result in scanner:
                if _BADGE_SERVICE_UUID in result.services():
#------------------ this is weird, pulls up an address of the found device
                    self.device_addr_scan = str(result.device) #hereeeeeeeeeee

                    print(f"Found device: {result.name()} RSSI: {result.rssi}")

                    try:
                        print("Connecting to device from find_other!")
                        connection = await result.device.connect()
                        return connection                      
                        
                    except asyncio.TimeoutError:
                        print("Timeout during connection")
                        return None
        return None

    #advertises all the time excluding the connection, this function shouldn't do anything besides advertising.
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
#-------------- this is weird, pulls up an address of the conected device
                self.device_addr_adv = str(connection.device)

                #this flags the good match if it is
                result_of_search = await self.evaluate_connection(connection)
                if result_of_search:
                    self.good_match.set()

                await connection.disconnected(timeout_ms=None)
    
    #honestly idk about this one
    #this function tries to read both addresses from adv and scan, and returns one of them 
    def get_address(self):
        addr_scan = self.device_addr_scan
        addr_adv = self.device_addr_adv
        if addr_scan == None:
            #idk this might be unnecessary debugging
            #set both addresses to None so that next time it goes from the same state
            self.device_addr_scan = None
            self.device_addr_adv = None
            return str(addr_adv)
        else:
            #idk this might be unnecessary debugging
            #set both addresses to None so that next time it goes from the same state
            self.device_addr_scan = None
            self.device_addr_adv = None
            return str(addr_scan)

    #returns a connection object from find_other, if fails returns None and catches an error 
    async def get_connection(self):
        try:
            connection = await self.find_other()
            return connection
        except Exception as e:
            print(f"Error from get_connection: {e}")
            return None

    #given the connection object, it returns if the match is good or not (True/False)
    #references decode_info and check_match
    async def evaluate_connection(self, connection):
        if connection.is_connected():

            #try connecting to a service, if None - return False 
            try:
                await asyncio.sleep_ms(200)
                self.badge_connection_service = await connection.service(_BADGE_SERVICE_UUID)

                if self.badge_connection_service is None:
                    print("Service not found!")
                    return False
                
                #sometimes it goes here even though the service is not found    
                self.info_connection_characteristic = await self.badge_connection_service.characteristic(_INFO_CHAR_UUID)
                print("Characteristic found successfully")

            except asyncio.TimeoutError:
                print("Timeout discovering services/characteristics")
                return False
            
            #when connected, read and decode    
            try:
                read_info = await self.info_connection_characteristic.read()
                read_info = decode_info(read_info)
                print("Information: ", read_info)
                await asyncio.sleep_ms(1000)

    #---------- this is also new, watch out
                #"immediatelly after" disconnect
                await connection.disconnect()
                print("Disconnected from device")

                if self.check_match(read_info) == 1:
                    #this writing is never used
                    led.on()
                    sleep(1) # sleep 1sec
                    led.off()
                    print("Finished evaluating connection.")
                    print()
                    return True
                else:
                    print("Finished evaluating connection.")
                    print()
                    return False

            except Exception as e:
                print(f"Unknown exception: {e}")
                try:
                    await connection.disconnect()
                except:
                    pass  # Ignore disconnection errors
                return False
        else:
            return False

    #given the array compares it with internal array
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
            return True
        else:
            print("Bad match")
            return False

    #needs attention: returns a number that is assigned to different distances in meters, weird function, doesn't do much
    def humanize_rssi(self, rssi):
#------ this function needs a lot of work!!! The distance values it gives rn aren't good enough.
        if rssi > -65:
            return 1
        elif rssi > -80:
            return 2
        elif rssi > -95:
            return 3
        elif rssi > -120:
            return 4
        else:
            return 5

#-- try this, also new
    def rssi_meters(self, rssi):
        return f"{10**((-50-rssi)/(10*2.5))}m"
    
    #based on the rssi, lights up different colors
    #references humanize_rssi
    async def get_distance_feedback(self, rssi):
        result = self.humanize_rssi(rssi)
        if result == 1:
            #something like flashing green
            led_color(1, 0, 0)  # Green
            await asyncio.sleep_ms(200)

        elif result == 2:
            #something like long green
            led_color(1, 0, 1)  # Yellow
            await asyncio.sleep_ms(200)

        elif result == 3:
            #something like a flashing yellow
            led_color(1, 1, 0)  # Cyan
            await asyncio.sleep_ms(200)

        elif result == 4:
            #something like a solid yellow
            led_color(0, 1, 0)  # Blue
            await asyncio.sleep_ms(200)

        elif result == 5:
            #something like a solid red, maybe actually if detects then maybe flashing red, otherwise - solid.
            led_color(0, 0, 1)  # Red
            await asyncio.sleep_ms(200)        
            
    #tracks the previously found match given its address, exits when reaches timeout
    #references rssi_meters, humanize_rssi, and get_distance_feedback
    async def search_with_scan(self, addr, timeout_s):
        
        print("Starting to track")
        start_time = time.time()
        target_rssi = -50
        print(f"Scanning for device proximity (target RSSI: {target_rssi})")
    
        while (time.time() - start_time) < timeout_s:
            #when the switch is on, find the device and track it, when done the loop is done.
#---------- this needs to be discussed.
            while not switch.value():  
                print("Switch off, skipping scan")
                await asyncio.sleep(1)
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
                                
                            #links to the function that gives a distance from the rssi
                            distance = self.rssi_meters(current_rssi)
                            print(f"Distance value: {distance}m")
                            print()

                            #lights
                            await self.get_distance_feedback(self.humanize_rssi(current_rssi)) 

                await asyncio.sleep_ms(1000)  # Wait between scan cycles
                
            except Exception as e:
                print(f"Error during proximity scanning: {e}")
                await asyncio.sleep_ms(2000)
                return False

        print("Proximity scanning time is over :(")
        return False         

    async def run_task(self):
        await self.setup_task()
        advertise = asyncio.create_task(self.advertise())

        while True:

            # Pause if the switch is OFF
            while not switch.value():
                print("Switch is OFF — Pausing...")
                await asyncio.sleep_ms(500)

            print("Switch is ON - Running proximity tasks.")

            #fencepost
            connection = await self.get_connection()
            if connection:
                result_of_search = await self.evaluate_connection(connection)
                if result_of_search:
                    self.good_match.set()

            #if the badge can't find a good match, try again until found (advertising should catch up)
            while not self.good_match.is_set():

#-------------- add a stopper here maybe?
                #if the switch is turned OFF, don't go further
                if not switch.value():
                    print("Switch turned OFF during matching - Pausing...")
                    await asyncio.sleep(0.5)
                    break  # Break out of this loop if switch goes off

                connection = await self.get_connection()
                if connection:
                    result_of_search = await self.evaluate_connection(connection)
                    if result_of_search:
                        self.good_match.set()

            #now the good_match is set, do the tracking - get the address, start tracking
            addr = self.get_address()
            print(addr)
            await asyncio.sleep_ms(500)

            if addr:
                result = await self.search_with_scan(addr, 40)
                if result:
                    print("Another connection made!!!")
                    await asyncio.sleep(2)

#---------- maybe add the "try again" loop?
            #this is the end of the loop^ it 

            # Reset match result for the next loop
            self.good_match.clear()

        # Should never reach here, but if you add a stop condition:
        await advertise

async def main():
    badge = Badge([1, 2, 0], "BBBBB")
    await badge.run_task()

asyncio.run(main())
