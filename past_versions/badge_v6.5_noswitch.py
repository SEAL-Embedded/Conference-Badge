

#no switch version!

from machine import Pin
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

switchScan = Pin(11, Pin.IN, Pin.PULL_DOWN)  # GP11 for scanning
switchAdvertise = Pin(10, Pin.IN, Pin.PULL_DOWN) # GP10 for advertising

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

        #for the lights loop
        self.tracking = False
        self.current_rssi = None

        #set and registed service and characteristics
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        self.info_characteristic = aioble.Characteristic(self.badge_service, _INFO_CHAR_UUID, read=True, notify=True)
        self.match_characteristic = aioble.Characteristic(self.badge_service, _MATCH_CHAR_UUID, read=True, write=True)

        aioble.register_services(self.badge_service)

#------ this set of already connected is not used currently 
        self.already_connected = set()

        #event setup
        self.good_match = asyncio.Event()
        self.connection_made = asyncio.Event()
        
        #this should be looked over, but debugging 
        self.addr = None
        self.device_addr_adv = None
        self.device_addr_scan = None

    #not sure if we need this fuciton now that I changed everything 
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
                    if not (result.device in self.already_connected):

                        print(f"Found device: {result.name()} RSSI: {result.rssi}")
                        try:
                            manufacturer_list = list(result.manufacturer(0xFFFF))
                            needed_data = manufacturer_list[0][1]
                            read_info = decode_info(needed_data)
                        except Exception as e:
                            print(f"Exception by not finding the manufacturer info: {e}")
                            print()
                            continue

                        #if the match is bad, don't do anything
                        if not self.check_match(read_info):
                            continue
                        
                        else:
#-------------------------- should flash something to indicate 
                            print("Found a good match!")
                            self.good_match.set()

                            #pulls up an address of the found device
                            self.device_addr_scan = str(result.device)

                            try:
                                print("Connecting to let them know!")
                                print()
                                connection = await result.device.connect()

                                print("Added to the set of already connected")
                                self.already_connected.add(result.device) #work with set

                                await asyncio.sleep_ms(500)
                                await connection.disconnect()
                                #think of ending this connection right there maybe?                   
                                
                            except asyncio.TimeoutError:
                                print("Timeout during connection")
                                return None
                    else:
                        await asyncio.sleep_ms(500)
                        print("Already connected to this device once!")
                        print()
#---------------------- do something with it
                        continue
        
        print("No good devices nearby")
        return None

    #advertises all the time excluding the connection, this function shouldn't do anything besides advertising.
    async def advertise(self):
        while True:
            #this block starts advertising and continues ONLY WHEN the connection is established
            #while not switchAdvertise.value():
            #    print("Switch off: skipping advertising")
            #    await asyncio.sleep_ms(1000)

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

#-------------- should flash something to indicate
                print("Advertising found connection!, from:", connection.device)
                print()
                #this flags the good match, should already be a good match if connected
                self.good_match.set()
                self.already_connected.add(connection.device) #work with set

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

    #formula. good, but the constants can be different
    def rssi_meters(self, rssi):
        return f"{10**((-50-rssi)/(10*3.5))}"
    
    #based on the rssi, lights up different colors
    #references humanize_rssi
    async def distance_feedback_loop(self):
        while True:
            if self.connection_made.is_set():
                break

            if self.tracking and self.current_rssi is not None:
                rssi = self.current_rssi
                print(rssi)

                #turn on
                led_color(1, 0, 0)  # Red (or adjust as needed)

                # Adjust blink rate based on signal strength
                if rssi > -60:
                    await asyncio.sleep_ms(200)
                elif rssi > -70:
                    await asyncio.sleep_ms(400)
                elif rssi > -80:
                    await asyncio.sleep_ms(600)
                else:
                    await asyncio.sleep_ms(800)

                #turn off
                led_off()

                if rssi > -60:
                    await asyncio.sleep_ms(200)
                elif rssi > -70:
                    await asyncio.sleep_ms(400)
                elif rssi > -80:
                    await asyncio.sleep_ms(600)
                else:
                    await asyncio.sleep_ms(800)

            else:
                # Ensure LED is OFF when not tracking
                led_off()
                await asyncio.sleep_ms(100)

    async def celebration_lights(self):
        led_color(1, 0, 0) 
        await asyncio.sleep_ms(500)
        led_color(0, 1, 0) 
        await asyncio.sleep_ms(500)
        led_color(0, 0, 1) 
        await asyncio.sleep_ms(500)
        led_color(1, 1, 0) 
        await asyncio.sleep_ms(500)
        led_color(1, 0, 1) 
        await asyncio.sleep_ms(500)
        led_color(0, 1, 1) 
        await asyncio.sleep_ms(500)
        led_color(1, 1, 1) 
        await asyncio.sleep_ms(500)
        led_off()

    #tracks the previously found match given its address, exits when reaches timeout
    #references rssi_meters, humanize_rssi, and get_distance_feedback
    #target_rssi can be different and should be looked over
    async def search_with_scan(self, addr, timeout_s):

        self.connection_made.clear()    #OK to start the LED loop
        lights_loop = asyncio.create_task(self.distance_feedback_loop())
        
        print("Starting to track")
        start_time = time.time()
        target_rssi = -48
        print(f"Scanning for device proximity (target RSSI: {target_rssi})")
        print()
    
        while (time.time() - start_time) < timeout_s:
            #when the switch is on, find the device and track it, when done the loop is done.
#---------- this still needs to be discussed.
            target_count = 0
            #if not switchScan.value(): 
            #    print("Switch off, exiting the tracking loop")
            #    await asyncio.sleep(1)
            #    break

            try:
                #scan duration is 1.5 seconds now
                async with aioble.scan(1500, interval_us=30000, window_us=30000, active=True) as scanner:
                    async for result in scanner:
                        if str(result.device) == str(addr):

                            self.current_rssi = result.rssi     #both start
                            self.tracking = True                #the LED loop

                            print(f"Found targeted device! RSSI: {self.current_rssi}")                            
                            
                            #if reached target
                            if self.current_rssi > target_rssi:
                                print("Target reached!")
                                target_count += 1
                                if target_count >= 2:   #just to make sure they met

                                    self.connection_made.set()      #stop this LED loop immediatelly 
                                    self.tracking = False           #also clear these fields
                                    self.current_rssi = None 

                                    print()
                                    print("************||************")
                                    print("Another connection made!!!")
                                    print("************||************")
                                    print()      
                                    
                                    await self.celebration_lights()
                                    return True
                                
                                else:
                                    #if this is the first encounter
                                    #actually I don't know if this is needed, we could just make the lights go longer
                                    print()
                                    continue

                                                                
                            #links to the function that gives a distance from the rssi
                            distance = self.rssi_meters(self.current_rssi)
                            print(f"Distance value: {distance}m")
                            print()

                            #this is to exit the scanning loop and start scanning again
                            break

                await asyncio.sleep_ms(500)  # Wait between scan cycles
                
            except Exception as e:
                print(f"Error during proximity scanning: {e}")
                await asyncio.sleep_ms(2000)
                return False

        print("Proximity scanning time is over :(")
        lights_loop.cancel()   #this stops it completelly     
        self.tracking = False
        self.current_rssi = None
        return False           

    async def run_task(self):
        await self.setup_task()
        #advertises only if the switch is on
        advertise = asyncio.create_task(self.advertise())

        while True:
            #if switch is not ON, wait 1 sec
            #while not switchScan.value():
            #    print("Switch off: skipping scanning")
            #    await asyncio.sleep_ms(1000)

            try:
                await self.find_other()
                await asyncio.sleep_ms(500)
            except Exception as e:
                print(f"Error from calling find_other(): {e}")

            if not self.good_match.is_set():
                continue    #try find_other() again, or get the connection

            else:
                #now the good_match is set, get the address and start tracking
                addr = self.get_address()
                #print(addr)
                if addr is None:
                    print("You're stupid, it doesn't work like that ~>.<~")
                    continue

                await asyncio.sleep_ms(500)

                #20 seconds now!!!
                result = await self.search_with_scan(addr, 20)
                while not result:
                    #check if the switch is still on
                    #if switchScan.value():
                    #    print("Try again")
                        result = await self.search_with_scan(addr, 20)
                        print("Trying again")
                        await asyncio.sleep(2)
                    #else:
                    #    break       #so right here, if the people didn't meet and switch is OFF it exits the loop

                await asyncio.sleep(2)

            #program should not exit the serching loop until found the device. 
            #If the user wants to give up on finding this exact match, they can turn off/on(if from advertising) 
            #the searching switch and turn it back on/off again to start over

            #this is the end of the loop^ 

            # Reset match result for the next loop
            self.good_match.clear()

        # Should never reach here, but if you add a stop condition:
        await advertise

async def main():
    badge = Badge([1, 2, 0], "BBBB")
    await badge.run_task()

try: 
    asyncio.run(main())
except KeyboardInterrupt:
    led_off()
    print("Program interrupted. LED turned off.")
