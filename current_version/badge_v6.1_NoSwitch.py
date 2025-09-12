
#no switch version!

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
#-- Claude says it should not be 3
    turnOn.value(1)

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
    def __init__(self, info_array, name=None):

        #set info attributes
        self.set_info = info_array
        self.adv_packet = encode_info(info_array)
        self.set_badgename = name

        #set and registed service and characteristics
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        self.info_characteristic = aioble.Characteristic(self.badge_service, _INFO_CHAR_UUID, read=True, notify=True)
        self.match_characteristic = aioble.Characteristic(self.badge_service, _MATCH_CHAR_UUID, read=True, write=True)

        aioble.register_services(self.badge_service)

#------ this is very weird, for what?
        self.addr = None

#------ this set of already connected is not used currently 
        self.already_connected = set()

        #event setup
        self.good_match = asyncio.Event()
        
        #this should be looked over 
        self.device_addr_adv = None
        self.device_addr_scan = None

    #not sure about this fuciton now that I changed everything 
    async def setup_task(self):
        await asyncio.sleep_ms(500)
        print(f"Badge {self.set_badgename} is set up.")
        print()
        await asyncio.sleep_ms(500)

    #scans for the devices with the set service, returns connection object if match is good, returns None otherwise
    async def find_other(self):
        async with aioble.scan(5000, interval_us=30000, window_us=20000, active=True) as scanner:
            async for result in scanner:
                if _BADGE_SERVICE_UUID in result.services():

                    print(f"Found device: {result.name()} RSSI: {result.rssi}")
                    try:
                        read_info = decode_info(result.manufacturer(0xFFFF))
                    except Exception as e:
                        print(f"Exception by not finding the manufacturer info: {e}")
                        continue

                    #if the match is bad, don't do anything
                    if not self.check_match(read_info):
                        continue
                    
                    else:
                        print("Found a good match!")
                        self.good_match.set()

                        #pulls up an address of the found device
                        self.device_addr_scan = str(result.device)

#---------------------- this is unknown. watch out
                        self.already_connected.add(result.device)

                        try:
                            print("Connecting to let them know!")
                            connection = await result.device.connect()
                            return connection                      
                            
                        except asyncio.TimeoutError:
                            print("Timeout during connection")
                            return None

                    #think about reading the adv_data (advanced advertising?)
        return None

    #advertises all the time excluding the connection, this function shouldn't do anything besides advertising.
    async def advertise(self):
        while True:
            #this block starts advertising and continues ONLY WHEN the connection is established
            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=self.set_badgename,
                services=[_BADGE_SERVICE_UUID],
                manufacturer=(0xFFFF, self.adv_packet),
                appearance=0,
            ) as connection:

                #so ig with the new functionality the connection should only be requested when the match is good...
                #yeah, and this doesn't need to know the name of the badge since if the 
#-------------- this is a bad assumption. but if the match is good from one side it should be good on the other side too
                #so no worries for now about the name in the advertising

                print("Advertising found connection!, from:", connection.device)
                #this flags the good match, should already be a good match if connected!
                self.good_match.set()

                #this is weird, pulls up an address of the conected device
                self.device_addr_adv = str(connection.device)

                await connection.disconnected(timeout_ms=None)
    
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
        #not elif for some reason
        else:
            #idk this might be unnecessary debugging
            #set both addresses to None so that next time it goes from the same state
            self.device_addr_scan = None
            self.device_addr_adv = None
            return str(addr_scan)

    #given the array compares it with internal array
    def check_match(self, read_info):
        match = 0
        if read_info[0] == self.set_info[0]:
            match += 1
        if read_info[1] == self.set_info[1]:
            match += 1
        if read_info[2] == self.set_info[2]:
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
        return f"{10**((-50-rssi)/(10*4))}m"
    
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
            #while not switch.value():  
            #    print("Switch off, wait till the end of the tracking loop")
            #    await asyncio.sleep(1)

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

                            #this is to exit the scanning loop and start scannign again
                            break
                        
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

            try:
                await self.find_other()
            except Exception as e:
                print(f"Error from calling find_other(): {e}")

            if not self.good_match.is_set():
                continue
            else:
                #now the good_match is set, do the tracking - get the address, start tracking
                addr = self.get_address()
                print(addr)
                if addr is None:
                    print("You're stupid, it doesn't work like that ~>.<~")
                    continue

                await asyncio.sleep_ms(500)

                #there should be a condition checking if the address is None, but I removed it 
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
