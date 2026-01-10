
#see if the result.device is consistent with the format of the set /in search_with_scan

#the is_tracking should be looked over, (maybe add the new "not_available") 
# because it influences the internal array that's passed to the advertising

#there are a lot of random delays (awaits), maybe check them out

#add the color choosing part to the manufacturer data in the advertising (needs hardware)

#no switch version!

from machine import Pin
from utime import sleep
import bluetooth
import aioble
import asyncio
import struct
import time
import urandom

_BADGE_SERVICE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")
_INFO_CHAR_UUID = bluetooth.UUID("aa01b013-dcea-4880-9d89-a47e76c69c3c")
_MATCH_CHAR_UUID = bluetooth.UUID("2aca7f5b-02b7-4232-a5f0-56cb9155be7a")

# How frequently to send advertising beacons.
_ADV_INTERVAL_MS = 250_000

led = Pin(2, Pin.OUT)

#switchScan = Pin(11, Pin.IN, Pin.PULL_DOWN)  # GP11 for scanning
#switchAdvertise = Pin(10, Pin.IN, Pin.PULL_DOWN) # GP10 for advertising

''' legend for the "roles" (?):
degree = o if hs
degree = 1 if undergrad
degree = 2 if graduate

major
area of study (research)
speaker/attendee
undergrad/masters/phd/professional
company affiliation (boeing/?/etc)

'''

'''
#get the LED
red = Pin(12, Pin.OUT)
green = Pin(10, Pin.OUT)
blue = Pin(11, Pin.OUT)
turnOn = Pin(13, Pin.OUT)

led = Pin(2, Pin.OUT)

def led_off():
    red.value(1)
    green.value(1)
    blue.value(1)

def led_color(integerr, g, b):
    # Inverted logic for common anode
    r = (x >> 2) & 1  # Most significant bit (leftmost)
    g = (x >> 1) & 1  # Middle bit
    b = x & 1         # Least significant bit (rightmost)

    red.value(0 if r else 1)
    green.value(0 if g else 1)
    blue.value(0 if b else 1)
    turnOn.value(1)
'''


def encode_array(info_list):
    # Use 'b' (signed byte) instead of 'h' (short)
    format_str = "<" + "b" * len(info_list)
    return struct.pack(format_str, *[int(x) for x in info_list])

def decode_array(message):
    num_fields = len(message)  # Each 'b' is 1 byte
    format_str = "<" + "b" * num_fields
    return list(struct.unpack(format_str, message))

class Badge:
    #this creates fields for the Badge object, including the name, info_array and service with characteristic
    def __init__(self, info_array, find_this, match_tolerance, name=None):

        #set info attributes
        self.is_tracking = False
        self.set_badgename = name
        self.match_tolerance = match_tolerance
        self.target_rssi = -48
        self.timeout_s = 10
        self.number_of_elements = 10 #length of the info array 
        self.color_set = self.color()
        #(honestly, better use a set number of elements and pass -1s when not filled out)
        self.set_info = self._pad_array(info_array)
        self.set_target = self._pad_array(find_this)
        self.adv_name = encode_array(self.set_info)
        self.adv_target = encode_array(self.set_target)

        #for the lights loop
        self.current_rssi = None

        #set and registed service and characteristics
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        self.info_characteristic = aioble.Characteristic(self.badge_service, _INFO_CHAR_UUID, read=True, notify=True)
        self.match_characteristic = aioble.Characteristic(self.badge_service, _MATCH_CHAR_UUID, read=True, write=True)

        aioble.register_services(self.badge_service)

#------ this set of already connected is not used currently 
        self.already_connected = set()

        #event setup
        self.connection_made = asyncio.Event()          #if connection is made by scanning
        self.connection_made_for_1 = asyncio.Event()    #if connection is made by advertising
        self.search_is_going = asyncio.Event() 
        self.target_reached = asyncio.Event()           #if devices came to a close proximity
        
        #this should be looked over, but debugging 
        self.addr = None
        self.device_addr_adv = None
        self.device_addr_scan = None

    #to fill up the array with -1s
    def _pad_array(self, arr):
        """Pad array with -1s to reach number_of_fields"""
        if len(arr) < self.number_of_elements:
            return arr + [-1] * (self.number_of_elements - len(arr))
        return arr[:self.number_of_elements]  # Truncate if too long

    def color(self):
        while True:
        # get 3 random bits as a single integer
        x = urandom.getrandbits(3)  # returns 0..7
        if x != 0:  # avoid 000
            return x
    
    # Convert integer n to an integer representing its binary digits, i.e. 7 becomes 111
    def int_to_binary_int(n, bits=3):
        return int(f"{n:0{bits}b}")

    #not sure if we need this fuciton now that I changed everything 
    async def setup_task(self):
        await asyncio.sleep_ms(500)
        print(f"Badge {self.set_badgename} is set up.")
        print()
        await asyncio.sleep_ms(500)

    #scans for the devices with the set service, returns connection object if match is good, returns None otherwise
    async def find_other(self):
        async with aioble.scan(1000, interval_us=30000, window_us=20000, active=True) as scanner:
            async for result in scanner:
                if _BADGE_SERVICE_UUID in result.services():
                    #print(f"result.device type: {type(result.device)}")     # (debugging) or just remove those completelly
#------------------ remove and if anything
                    if not (result.device in self.already_connected) and not (self.connection_made_for_1.is_set()):

                        print(f"Found device: {result.name()} RSSI: {result.rssi} Address: {result.device}")
                        print()

                        if (result.rssi < -100):
                            continue

                        try:
                            # Get the generator + convert it to list
                            manufacturer_gen = result.manufacturer(0xFFFF)
                            manufacturer_list = list(manufacturer_gen)
                            
                            # Check if list is empty
                            if not manufacturer_list:
                                print("Empty manufacturer list - no data for company ID 0xFFFF")
                                continue

                            # The manufacturer data is likely the first (and probably only) item
                            manufacturer_data = bytes(manufacturer_list[0][1])
                            is_tracking = bool(manufacturer_data[0])
                            their_tolerance = int(manufacturer_data[1])
                            their_color = int(manufacturer_data[2])
                            print(f"is_tracking: {is_tracking}")
                            print(f"their match_tolerance: {their_tolerance}")  # Debug print
                            print()


                            #if already tracks other device, don't distract it, try other device
                            if is_tracking:
                                print("Device is in tracking mode, don't connect")
                                print()
                                continue
                            
                            info_byte_len = len(self.set_info)
                            target_byte_len = len(self.set_target)
                            
                            info_bytes = manufacturer_data[3:3 + info_byte_len]
                            target_bytes = manufacturer_data[3 + info_byte_len:3 + info_byte_len + target_byte_len]
                            
                            #somewhere here would go the color setting

                            #somewhere here would go the threshold match

                            read_info = decode_array(info_bytes)
                            read_target = decode_array(target_bytes)
                            print(f"their tags: {read_info}, they are looking for: {read_target}")

                        except Exception as e:
                            print(f"Exception with the manufacturer info: {e}")
                            print()
                            continue

                        #if the match is bad, don't do anything
                        if not self.check_match(read_info):
                            continue
                        
                        else:
                            if not self.check_IAM_match(read_target, their_tolerance):
                                continue
#-------------------------- should flash something to indicate 
                            print("Found a good match on both sides! ")

                            #pulls up an address of the found device
                            self.device_addr_scan = str(result.device)

                            try:
                                print("Connecting to let them know!")
                                print()
                                connection = await result.device.connect()

                                self.connection_made.set()

                                await asyncio.sleep_ms(500)
                                await connection.disconnect()
                                #think of ending this connection right there maybe?                   
                                
                            except asyncio.TimeoutError:
                                print("Timeout during connection")
                                return None
                            
                    elif (self.connection_made_for_1.is_set()):
                        await asyncio.sleep_ms(500)
                        print("Device is found from advertising")
                        return True
                    
                    else:
                        print("Already connected to this device once!")
                        await asyncio.sleep_ms(1000)
                        print()
#---------------------- do something with it
                        continue
        
        print("No good devices nearby *or exited the scanning loop")
        return None

    #advertises all the time excluding the connection, this function shouldn't do anything besides advertising.
    async def advertise(self):
        while True:
            #this block starts advertising and continues ONLY WHEN the connection is established
            #while not switchAdvertise.value():
            #    print("Switch off: skipping advertising")
            #    await asyncio.sleep_ms(1000)
            
            tracking_byte = struct.pack('B', int(self.is_tracking))
            tolerance_byte = struct.pack('B', self.match_tolerance)
            color_byte = struct.pack('B', self.color_set)
            manufacturer_data = tracking_byte + tolerance_byte + color_byte + self.adv_name + self.adv_target 

            #print(f"Sending manufacturer data: {manufacturer_data}")       #debugging
            #print(f"Length: {len(manufacturer_data)}")                     #debugging

            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=self.set_badgename,
                services=[_BADGE_SERVICE_UUID],
                manufacturer=(0xFFFF, manufacturer_data),
                appearance=0,
            ) as connection:
        
#-------------- should flash something to indicate? (for trials without switch)
                print("Advertising found connection!, from:", connection.device)
                print()

                self.connection_made_for_1.set()

                #this is weird, pulls up an address of the conected device
                #from Claude

                device_str = str(connection.device)
                # Remove the ", CONNECTED)" part
                clean_str = device_str.rsplit(', ', 1)[0] + ')'

                self.device_addr_adv = str(clean_str)
                #print(self.device_addr_adv)    #debugging

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

    def check_match(self, read_info):
        match = 0
        compared = 0  # Track how many non-(-1) comparisons we made
        
        for i in range(self.number_of_elements):
            # Skip if either value is -1
            if self.set_target[i] == -1 or read_info[i] == -1:
                continue
                
            compared += 1  # Count this as a valid comparison
            if read_info[i] == self.set_target[i]:
                match += 1

        # Need at least (compared - tolerance) matches
        # But only if we had enough comparisons
        if compared == 0:
            print("No valid fields to compare!")
            return False
            
        if match >= compared - self.match_tolerance:
            print(f"Good match from their side! ({match}/{compared} matched)")
            return True
        else:
            print(f"Bad match from their side :( ({match}/{compared} matched)")
            return False
        
    def check_IAM_match(self, read_target, their_tolerance):
        match = 0
        compared = 0
        
        for i in range(self.number_of_elements):
            # Skip if either value is -1
            if self.set_info[i] == -1 or read_target[i] == -1:
                continue
                
            compared += 1
            if read_target[i] == self.set_info[i]:
                match += 1

        if compared == 0:
            print("No valid fields to compare!")
            return False
            
        if match >= compared - their_tolerance:
            print(f"Good match from your side! ({match}/{compared} matched)")
            return True
        else:
            print(f"Bad match from your side :( ({match}/{compared} matched)")
            return False

    #formula. good, but the constants can be different 
    def rssi_meters(self, rssi):
        return f"{10**((-50-rssi)/(10*3.5))}"
    
    #based on the rssi, lights up different frequencies with the color chosen by the pair
    #RSSI values also here
    async def distance_feedback_loop(self):
        while True:

            if not self.search_is_going.is_set(): #if search with scan is not going
                await asyncio.sleep_ms(200) #so it doesn't waste to much
                break

#---------- lets look at the "tracking"
            if self.is_tracking and self.current_rssi is not None: 
                #and not (self.target_reached.is_set()):
                #which is only valid if we want to have a fancy feedback for the target_reached part
                
                rssi = self.current_rssi

                #HARDWARE 
                a = 100
                #Adjust blink rate based on signal strength
                led.value(1)  # Red is 001, blue is 010, green is 100 (or adjust as needed)
                await asyncio.sleep_ms(int(a*(10**((-50-rssi)/(10*3.5)))))
                led.value(0)
                await asyncio.sleep_ms(int(a*(10**((-50-rssi)/(10*3.5)))))


            #elif self.target_reached.is_set(): #only if we want to differentiate the feedback
                #led_color(0, 0, 1) #we need an actual red
                #await asyncio.sleep_ms(400)
                #led_off()
                #await asyncio.sleep_ms(400)

            else:
                # Ensure LED is OFF when not tracking
                led.value(0)
                await asyncio.sleep_ms(100)

    #right now targets no additional hardware (change when get the pcb)
    async def celebration_lights(self):
        #led_color(1, 0, 0)             #green
        #await asyncio.sleep_ms(1000)

        #HARDWARE
        led.value(1)
        await asyncio.sleep_ms(2000)
        led.value(0)

    #tracks the previously found match given its address, exits when reaches timeout
    #target_rssi can be different and should be looked over
    async def search_with_scan(self, addr):

        self.connection_made_for_1.clear()      #clear the event for searching
        self.connection_made.clear()            #debugging prob?
        #self.target_reached.clear()            #clear the event for debugging

        self.search_is_going.set()    #OK to start the LED loop
        lights_loop = asyncio.create_task(self.distance_feedback_loop())
        
        print()
        print("Starting to track")
        print(f"Scanning for device proximity (target RSSI: {self.target_rssi})")
        print(f"this is the address it searches for: {addr}")
        print()

        start_time = time.time()
    
        while (time.time() - start_time) < self.timeout_s: #timeout is how long we want to keep trying
            #when the switch is on, find the device and track it, when done the loop is done.
            target_count = 0 

            #HARDWARE
            #if not switchScan.value(): 
            #    print("Switch off, exiting the tracking loop")
            #    await asyncio.sleep(1)
            #    break

            try:
                #scan duration is 1.5 seconds now
                async with aioble.scan(1500, interval_us=30000, window_us=30000, active=True) as scanner:
                    async for result in scanner:
                        #print("well, at least it is scanning")      #debugging
                    
                        if str(result.device) == str(addr):

                            self.current_rssi = result.rssi     #both start
                            self.is_tracking = True             #the LED loop and protection from connection

                            print(f"Found targeted device! RSSI: {self.current_rssi}")                            
                            
                            #if reached target
                            if self.current_rssi > self.target_rssi:

                                print("Target reached!")
                                self.target_reached.set()
                                target_count += 1

                                #wait before trying again 
                                await asyncio.sleep_ms(100)

                                #returns true
                                if target_count >= 2:   #just to make sure they met
    
                                    self.target_reached.clear()
                                    self.search_is_going.clear()      #stop this LED loop immediatelly 

                                    print()
                                    print("************||************")
                                    print("Another connection made!!!")
                                    print("************||************")
                                    print()  

                                    print("Added to the set of already connected")
                                    self.already_connected.add(result.device)       #work with set
                                     
                                    #turn on the celebration lights
                                    await self.celebration_lights()
                                    #random delay
                                    await asyncio.sleep_ms(500)

                                    self.is_tracking = False          #also clear these fields
                                    self.current_rssi = None 

                                    return True
                                
                                #if this is the first encounter, continue
                                else:
                                    print()
                                    continue

                            #if devices aren't close enough, restart the count
                            else:
                                target_count = 0
                                self.target_reached.clear()

                                                                
                            #links to the function that gives a distance from the rssi
                            distance = self.rssi_meters(self.current_rssi)
                            print(f"Approximated distance: {distance}m")

                            await asyncio.sleep_ms(500) 
                            print()

                            #this is to exit the scanning loop and start scanning again
                            break

                await asyncio.sleep_ms(500)  # Wait between scan cycles
                
            except Exception as e:
                print(f"Error during proximity scanning: {e}")
                await asyncio.sleep_ms(2000)
                return False

        #if during the allowed time interval the match was not found-
        print("Proximity scanning time is over :(")
        lights_loop.cancel()   #this stops it completelly     
        self.is_tracking = False
        self.current_rssi = None
        return False           

    async def run_task(self):
        await self.setup_task()
        #advertises only if the switch is on
        advertise = asyncio.create_task(self.advertise())

        while True:

            #HARDWARE
            #if switch is not ON, wait 1 sec
            #while not switchScan.value():
            #    print("Switch off: skipping scanning")
            #    await asyncio.sleep_ms(1000)

            #scans and listens interchangibly every 1s
            try:
                await self.find_other()
                await asyncio.sleep_ms(1000)

            except Exception as e:
                print(f"Error from calling find_other(): {e}")

            if (not self.connection_made.is_set()) and (not self.connection_made_for_1.is_set()):
                continue #try find_other again

            #now the connection is made, get the address and start tracking
            addr = self.get_address()
            if addr is None:
                print("You're stupid, it doesn't work like that ~>.<~")
                continue
            
            #random delay?
            await asyncio.sleep_ms(500)
            result = await self.search_with_scan(addr)
            count_of_tries = 0
            while not result and count_of_tries < 5:
                    
                #HARDWARE
                #check if the switch is still on
                #if switchScan.value():
                #    print("Try again")

                    result = await self.search_with_scan(addr)
                    count_of_tries += 1
                #else:
                    #break       #so right here, if the people didn't meet and switch is OFF it exits the loop

            await asyncio.sleep(2)


            #program should not exit the serching loop until found the device. 
            #If the user wants to give up on finding this exact match, they can turn off/on(if from advertising) 
            #the searching switch and turn it back on/off again to start over

            #this is the end of the loop^ 

            # Reset match result for the next loop
            self.connection_made.clear()
            self.connection_made_for_1.clear()

        # Should never reach here, but if you add a stop condition:
        await advertise

async def main():
    badge = Badge([1, 2, 0], [1, 2, 0], 1, "BBBB")
    await badge.run_task()

try: 
    asyncio.run(main())

except KeyboardInterrupt:
    led.value(0)
    print("Program interrupted. LED turned off.")
