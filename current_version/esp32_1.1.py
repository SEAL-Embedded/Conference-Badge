
#check if the is_tracking is consistent in the code

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
red = Pin(25, Pin.OUT)
green = Pin(26, Pin.OUT)
blue = Pin(14, Pin.OUT)
turnOn = Pin(27, Pin.OUT)

led = Pin(2, Pin.OUT)

def led_off():
    red.value(1)
    green.value(1)
    blue.value(1)

def led_color(r, g, b):
    # Inverted logic for common anode
    red.value(0 if r else 1)
    green.value(0 if g else 1)
    blue.value(0 if b else 1)
    turnOn.value(1)

#switchScan = Pin(11, Pin.IN, Pin.PULL_DOWN)  # GP11 for scanning
#switchAdvertise = Pin(10, Pin.IN, Pin.PULL_DOWN) # GP10 for advertising


''' legend for the "roles" (?):
degree = o if hs
degree = 1 if undergrad
degree = 2 if graduate'''


def encode_array(info_list):
    # Pack multiple values into one message
    format_str = "<" + "h" * len(info_list)
    return struct.pack(format_str, *[int(x) for x in info_list])

def decode_array(message):
    # Unpack multiple values from message
    num_fields = len(message) // 2  # Each 'h' is 2 bytes
    format_str = "<" + "h" * num_fields
    return list(struct.unpack(format_str, message))

class Badge:
    #this creates fields for the Badge object, including the name, info_array and service with characteristic
    def __init__(self, info_array, find_this, name=None):

        #set info attributes
        self.set_info = info_array
        self.set_target = find_this
        self.adv_name = encode_array(info_array)
        self.adv_target = encode_array(find_this)
        self.is_tracking = False
        self.set_badgename = name

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
        self.good_match = asyncio.Event()
        self.connection_made = asyncio.Event()
        self.connection_made_for_1 = asyncio.Event()
        #self.connection_found = asyncio.Event()
        
        #this should be looked over, but debugging 
        self.addr = None
        self.device_addr_adv = None
        self.device_addr_scan = None

        self.smoothed_rssi = None

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
                            print(f"is_tracking: {is_tracking}")
                            print()

                            #if already tracks other device, don't distract it, try other device
                            if is_tracking:
                                print("Device is in tracking mode, don't connect")
                                print()
                                continue
                            
                            info_byte_len = len(self.set_info) * 2
                            target_byte_len = len(self.set_target) * 2
                            
                            info_bytes = manufacturer_data[1:1 + info_byte_len]
                            target_bytes = manufacturer_data[1 + info_byte_len:1 + info_byte_len + target_byte_len]
                            
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
                            if not self.check_IAM_match(read_target):
                                continue
#-------------------------- should flash something to indicate 
                            print("Found a good match on both sides! ")
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
            manufacturer_data = tracking_byte + self.adv_name + self.adv_target

            #print(f"Sending manufacturer data: {manufacturer_data}")       #debugging
            #print(f"Length: {len(manufacturer_data)}")                     #debugging

            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=self.set_badgename,
                services=[_BADGE_SERVICE_UUID],
                manufacturer=(0xFFFF, manufacturer_data),
                appearance=0,
            ) as connection:

#-------------- this is a bad assumption. but if the match is good from one side it should be good on the other side too
        
#-------------- should flash something to indicate? (for trials without switch)
                print("Advertising found connection!, from:", connection.device)
                print()
                #this flags the good match, should already be a good match if connected
                self.good_match.set()
                add = connection.device
                self.already_connected.add(add) #work with set
                self.connection_made_for_1.set()

                #this is weird, pulls up an address of the conected device
                #looks like this just got addressed
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

    #given the name array compares it with internal target array
    def check_match(self, read_info):
        match = 0
        if read_info[0] == self.set_target[0]:
            match += 1
        if read_info[1] == self.set_target[1]:
            match += 1
        if read_info[2] == self.set_target[2]:
            match += 1

        if match >= 2:
            print("Good match from their side!")
            return True
        else:
            print("Bad match from their side :(")
            return False
        
    #given the target array compares it with self.set_info array
    def check_IAM_match(self, read_target):
        match = 0
        if read_target[0] == self.set_info[0]:
            match += 1
        if read_target[1] == self.set_info[1]:
            match += 1
        if read_target[2] == self.set_info[2]:
            match += 1

        if match >= 2:
            print("Good match from your side!")
            return True
        else:
            print("Bad match from your side :(")
            return False

    #formula. good, but the constants can be different
#--------------------------------------------- work on the equation 
#rssi at one meter: 60
    def rssi_meters(self, rssi):
        return f"{10**((-60-rssi)/(10*2.5))}"

    def smooth_rssi(self, rssi, alpha=0.2):
        smoothed_rssi = self.smoothed_rssi
        if self.smoothed_rssi is None:
            self.smoothed_rssi = rssi  # initialize first value
        else:
            self.smoothed_rssi = alpha * rssi + (1 - alpha) * self.smoothed_rssi
        return smoothed_rssi



    
    #based on the rssi, lights up different colors
    #references humanize_rssi
#--------------------------------------------- RSSI values also here
    async def distance_feedback_loop(self):
        while True:
            if self.connection_made.is_set():
                break
#---------- lets look at the "tracking"
            if self.is_tracking and self.current_rssi is not None: #and not (self.connection_found.is_set()):
                rssi = self.current_rssi

                #turn on
                led_color(1, 0, 0)  # Red is 001, blue is 010, green is 100 (or adjust as needed)

                #Adjust blink rate based on signal strength
#-------------- These values are not right
                if rssi > -60:
                    await asyncio.sleep_ms(200)

                    led_off()
                    await asyncio.sleep_ms(200)

                elif rssi > -70:
                    await asyncio.sleep_ms(400)
                    led_off()
                    await asyncio.sleep_ms(400)

                elif rssi > -80:
                    await asyncio.sleep_ms(600)
                    led_off()
                    await asyncio.sleep_ms(600)

                else:
                    await asyncio.sleep_ms(800)
                    led_off()
                    await asyncio.sleep_ms(800)

            #elif self.connection_found.is_set():
                #led_color(0, 0, 1) #we need an actual red
                #await asyncio.sleep_ms(400)
                #led_off()
                #await asyncio.sleep_ms(400)

            else:
                # Ensure LED is OFF when not tracking
                led_off()
                await asyncio.sleep_ms(100)

    async def celebration_lights(self):
        #led_color(1, 0, 0)             #green
        #await asyncio.sleep_ms(1000)
        led_color(0, 1, 0)              #blue
        await asyncio.sleep_ms(1000)
        #led_color(0, 0, 1)             #red
        #await asyncio.sleep_ms(500)
        #led_color(1, 1, 0)             #cyan
        #await asyncio.sleep_ms(500)
        led_color(1, 0, 1)              #yellow
        await asyncio.sleep_ms(500) 
        led_color(0, 1, 0)              #blue
        await asyncio.sleep_ms(1000)
        led_color(0, 1, 1)              #magenta
        await asyncio.sleep_ms(500)
        led_color(0, 1, 0)              #blue
        await asyncio.sleep_ms(1000)
        led_color(1, 1, 1)              #white
        await asyncio.sleep_ms(500)
        led_off()

    
    #tracks the previously found match given its address, exits when reaches timeout
    #references rssi_meters, humanize_rssi, and get_distance_feedback
    #target_rssi can be different and should be looked over
    async def search_with_scan(self, addr, timeout_s):

        self.connection_made_for_1.clear()      #clear the event for searching
        #self.connection_found.clear()           #clear the event for debugging

        self.connection_made.clear()    #OK to start the LED loop
        lights_loop = asyncio.create_task(self.distance_feedback_loop())
        
        print()
        print("Starting to track")
        start_time = time.time()
        target_rssi = -48
        print(f"Scanning for device proximity (target RSSI: {target_rssi})")
        print(f"this is the address it searches for: {addr}")
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

                        #print("well, at least it is scanning")      #debugging
                    
                        if str(result.device) == str(addr):

                            
                            self.current_rssi = result.rssi     #both start
                            self.is_tracking = True               #the LED loop

                            print(f"Found targeted device! RSSI: {self.current_rssi}")                            
                            
                            #if reached target
#-------------------------- idk if we need this protection -------------------------------
                            if self.current_rssi > target_rssi:
                                    print("Target reached!")
                                #target_count += 1

                                #see what this does
                                #await asyncio.sleep_ms(500)

                                #self.connection_found.set()
                                #if target_count >= 2:   #just to make sure they met

                                    #self.connection_found.clear()
                                    self.connection_made.set()      #stop this LED loop immediatelly 
                                    self.is_tracking = False          #also clear these fields
                                    self.current_rssi = None 

                                    print()
                                    print("************||************")
                                    print("Another connection made!!!")
                                    print("************||************")
                                    print()      
                                    
                                    await self.celebration_lights()
                                    return True
                                
                                #else:
                                    #if this is the first encounter
                                    #actually I don't know if this is needed, we could just make the lights go longer
                                    #print()
                                    #continue
                            #else:
                                #self.connection_found.clear()

                                                                
                            #links to the function that gives a distance from the rssi
                            
                            value_rssi = self.smooth_rssi(self.current_rssi)
                            distance = self.rssi_meters(value_rssi)
                            print(f"Approximated distance: {distance}m")

#-------------------------- lets see if this does anything
                            await asyncio.sleep_ms(500) 
                            
                            print()

                            #this is to exit the scanning loop and start scanning again
                            break

                await asyncio.sleep_ms(500)  # Wait between scan cycles
                
            except Exception as e:
                print(f"Error during proximity scanning: {e}")
                await asyncio.sleep_ms(2000)
                return False

        print("Proximity scanning time is over :(")
        lights_loop.cancel   #this stops it completelly     
        self.is_tracking = False
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
                result = await self.search_with_scan(addr, 10)
                while not result:
                    #check if the switch is still on
                    #if switchScan.value():
                    #    print("Try again")
                        result = await self.search_with_scan(addr, 10)
                    #else:
                        #break       #so right here, if the people didn't meet and switch is OFF it exits the loop

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
    badge = Badge([1, 2, 0], [1, 2, 0], "BBBB")
    await badge.run_task()

try: 
    asyncio.run(main())

except KeyboardInterrupt:
    led_off()
    print("Program interrupted. LED turned off.")
