
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

#ALL THE BELOW IS OUDATED:
#see if the result.device is consistent with the format of the set /in search_with_scan (looks like it is)
#the is_tracking should be looked over, (maybe add the new "not_available") 
# because it influences the internal array that's passed to the advertising
#there are a lot of random delays (awaits), maybe check them out
#check stop_advertising, maybe remove

#no switch version!

from machine import Pin, PWM
import bluetooth
import aioble
import asyncio
import struct
import time
import urandom
import sys
sys.stdout.buffer.write(b'') 

_BADGE_SERVICE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")
_INFO_CHAR_UUID = bluetooth.UUID("aa01b013-dcea-4880-9d89-a47e76c69c3c")
_MATCH_CHAR_UUID = bluetooth.UUID("2aca7f5b-02b7-4232-a5f0-56cb9155be7a")

# How frequently to send advertising beacons.
_ADV_INTERVAL_MS = 100_000

# Continuous scanning approach:
interval_us = 100000  # 100ms
window_us = 90000    # 90ms (scan almost entire interval)

led = Pin(2, Pin.OUT)

#get the recognition (pair) LED
red = Pin(13, Pin.OUT)
green = Pin(33, Pin.OUT)
blue = Pin(32, Pin.OUT)
switch = Pin(12, Pin.PULL_DOWN, Pin.PULL_UP)  # GP11 for scanning

#turn off the led
def led_off():
    red.value(1)
    green.value(1)
    blue.value(1)

#given the color_code, turn on the color
def led_set_color(color_code):
    """Set LED to a specific color (1-7)"""
    r = (color_code >> 2) & 1
    g = (color_code >> 1) & 1
    b = color_code & 1
    
    red.value(0 if r else 1)
    green.value(0 if g else 1)
    blue.value(0 if b else 1)
    turnOn.value(1)
    print("This displayed color is: ", color_code)

# Set the proximity tracking LED
r = PWM(Pin(25))
g = PWM(Pin(26))
b = PWM(Pin(27))
turnOn = Pin(14, Pin.OUT)
led = Pin(2, Pin.OUT)

r.freq(1000)
g.freq(1000)
b.freq(1000)

turnOn.value(1)

#some weird shit that works:
# Given floats between 0.0 and 1.0, sets the color of the LEDs
def set_rgb(rr, gg, bb):
    # ESP32 PWM is 16-bit: 0–65535
    r.duty_u16(int((1-rr) * 65535))
    g.duty_u16(int((1-gg) * 65535))
    b.duty_u16(int((1-bb) * 65535))
    
# Limits the possible values of the RGB 
def clamp(x, low = 0.0, high = 1.0):
    if x < low: return low
    if x > high: return high
    return x

def rgb_off():
    r.duty_u16(65535)
    g.duty_u16(65535)
    b.duty_u16(65535)

# Given an RSSI value, maps it to a float that represents its color and brightness
def show_rssi_color(rssi, matched):
    # Map RSSI from [-90 .. -40] → [0 .. 1]
    if not matched:
        # Not matched → (turn off and) full blue 
        rgb_off()
        return
    t = (rssi + 90) / 50
    t = clamp(t)

    # Red → Green gradient
    r_col = 1 - t
    g_col = t
    b_col = 0
    # brightness scaling (stronger signal = brighter)
    brightness = 0.2 + 0.8 * t

    set_rgb(r_col * brightness, g_col * brightness, b_col * brightness)

#my beloved arrays
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

        #general settings
        self.target_rssi = -48
        self.timeout_s = 10
        self.number_of_elements = 10 #length of the info array 
        self.color_set = self.color()

        #set info attributes
        self.set_badgename = name
        self.match_tolerance = match_tolerance
        self.set_info = self._pad_array(info_array)
        self.set_target = self._pad_array(find_this)
        self.adv_name = encode_array(self.set_info)
        self.adv_target = encode_array(self.set_target)

        #set and registed service 
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        aioble.register_services(self.badge_service)

        #variables/fields that WILL be updated.
        self.current_rssi = None    #for the lights loop
        self.is_tracking = False    #supposed to help with not connecting while tracking
        self.already_connected = set()

        #event setup
        self.connection_made = asyncio.Event()          #if connection is made by scanning
        self.connection_made_for_1 = asyncio.Event()    #if connection is made by advertising
        self.stop_advertising = asyncio.Event()         #if adv found connection, stop it
        self.search_is_going = asyncio.Event() 
        self.target_reached = asyncio.Event()           #if devices came to a close proximity
        
        #debugging (should be looked over) 
        self.addr = None
        self.device_addr_adv = None
        self.device_addr_scan = None

    #to fill up the array with -1s
    def _pad_array(self, arr):
        """Pad array with -1s to reach number_of_fields"""
        if len(arr) < self.number_of_elements:
            return arr + [-1] * (self.number_of_elements - len(arr))
        return arr[:self.number_of_elements]  # Truncate if too long
    
    #If for whatever reason they change their addresses writing in the new updates
    #THIS WILL CRASH EVERYTHING
    def _extract_mac_address(self, device):
        """Extract MAC address from device object consistently"""
        try:
            device_str = str(device)
            parts = device_str.split(', ')
            if len(parts) >= 2:
                mac = parts[1].rstrip(')').rstrip(', CONNECTED').strip()
                return mac
            else:
                print(f"Unexpected device format: {device_str}")
                return None
        except Exception as e:
            print(f"Error extracting MAC: {e}")
            return None
    
    #random color assignment
    def color(self):
        x = (urandom.getrandbits(3) % 7) + 1
        #debugging
        print("This device's color is: ", x)
        return x

    #For us to see how everything is set up, nothing really
    async def setup_task(self):
        await asyncio.sleep_ms(500)
        print(f"Badge {self.set_badgename}")
        print(f"Badge's self: {self.set_info}, target: {self.set_target}")

        #debugging
        led_set_color(7)
        rgb_off()

        print()
        await asyncio.sleep_ms(500)

    #scans for the devices with the set service, returns connection object if match is good, returns None otherwise
    async def find_other(self):
        async with aioble.scan(1500, interval_us, window_us, active=True) as scanner:
            async for result in scanner:
                if _BADGE_SERVICE_UUID in result.services():
                    #print(f"result.device type: {type(result.device)}")     # (debugging) or just remove those completelly
#------------------ remove and if anything

                    if result.device in self.already_connected:
                        print("Already connected to this device once!")
                        print()
                        await asyncio.sleep_ms(200)
                        continue

                    if self.connection_made_for_1.is_set():
                        await asyncio.sleep_ms(100)
                        print("Device is found from advertising")
                        continue

                    else:
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
                            print(f"their match_tolerance: {their_tolerance} and color {their_color}")  # Debug print
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

                        #if the match (on both sides!) is bad, don't do anything
                        if not self.check_match(read_info, read_target, their_tolerance):
                            continue
                        
                        else:
#-------------------------- should flash something to indicate 
                            print("Found a good match on both sides! ")                            
                            #pulls up an address of the found device
                            self.device_addr_scan = self._extract_mac_address(result.device)
                            
                            #self.device_addr_scan = str(result.device).split(', ')[1].rstrip(')')

                            # NEW: Random backoff to avoid simultaneous connections
                            await asyncio.sleep_ms(urandom.getrandbits(8))

                            try:
                                print("Connecting to let them know!")
                                print()
                                connection = await result.device.connect()
                                self.color_set = their_color

                                self.connection_made.set()

                                await asyncio.sleep_ms(200)
                                await connection.disconnect()
                                await asyncio.sleep_ms(200)
                                #think of ending this connection right there maybe?  

                                return True                 
                                
                            except asyncio.TimeoutError:
                                print("Timeout during connection")

                                if self.connection_made_for_1.is_set():
                                    print("Other device connected via advertising, continuing...")
                                    return True
                                else:
                                    self.device_addr_scan = None
                                    continue
        
        print("No good devices nearby *or exited the scanning loop")
        return None

    #advertises all the time excluding the connection, this function shouldn't do anything besides advertising.
    async def advertise(self):
        while True:
            if self.stop_advertising.is_set():
                await asyncio.sleep_ms(200)
                continue

            #this block starts advertising and continues ONLY WHEN the connection is established
            while not switch.value():
                print("Switch off: skipping advertising")
                await asyncio.sleep_ms(1000)
                continue

            tracking = self.is_tracking
            tolerance = self.match_tolerance
            color = self.color_set

            tracking_byte = struct.pack('B', int(tracking))
            tolerance_byte = struct.pack('B', tolerance)
            color_byte = struct.pack('B', color)

            manufacturer_data = tracking_byte + tolerance_byte + color_byte + self.adv_name + self.adv_target 

            #print(f"Sending manufacturer data: {manufacturer_data}")       #debugging
            #print(f"Length: {len(manufacturer_data)}")                     #debugging

            #extra power drain when tracking for adversiting
            _ADV_INTERVAL_MS = 50_000 if (self.is_tracking) else 100_000

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
                self.device_addr_adv = self._extract_mac_address(connection.device)

                #self.device_addr_adv = device_str #was here before str(clean_str)
                #print(self.device_addr_adv)    #debugging

                await connection.disconnected(timeout_ms=None)
                self.stop_advertising.set()
  
    #this function tries to read both addresses from adv and scan, and returns one of them 
    def get_address(self):
        addr_scan = self.device_addr_scan
        addr_adv = self.device_addr_adv
        #set both addresses to None so that next time it goes from the same state

        if addr_scan is not None:
            self.device_addr_scan = None
            self.device_addr_adv = None
            return addr_scan
        elif addr_adv is not None:
            self.device_addr_scan = None
            self.device_addr_adv = None
            return addr_adv
        elif addr_adv is not None and addr_scan is not None:
            print("WOW, this is real! ^8^ Got two addressed and taking the scan result.")
            self.device_addr_scan = None
            self.device_addr_adv = None
            return addr_scan
        else:
            return None

    #wrapping generic method
    def check_match_generic(self, tolerance, passed_array, passed_self, name = "not needed"):
        match = 0
        compared = 0  # Track how many non-(-1) comparisons we made

        for i in range(self.number_of_elements):
            # Skip if either value is -1
            if passed_self[i] == -1 or passed_array[i] == -1:
                continue
                
            compared += 1  # Count this as a valid comparison
            if passed_array[i] == passed_self[i]:
                match += 1

        # Need at least (compared - tolerance) matches
        # But only if we had enough comparisons
        if compared == 0:
            print("No valid fields to compare!")
            return False
            
        if match >= compared - tolerance:
            #print(f"Good match from {name} side! ({match}/{compared} matched)")
            return True
        else:
            #print(f"Bad match from {name} side :( ({match}/{compared} matched)")
            return False
    
    def check_match(self, read_info, read_target, their_tolerance):
        if not (self.check_match_generic(self.match_tolerance, read_info, self.set_target)):
            return False
        if not (self.check_match_generic(their_tolerance, read_target, self.set_info)):
            return False
        return True

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
                led_set_color(self.color_set)
                print(self.color_set)
                
                show_rssi_color(self.current_rssi, self.is_tracking)
                await asyncio.sleep_ms(int(a*(10**((-50-rssi)/(10*3.5)))))
                rgb_off()
                await asyncio.sleep_ms(int(a*(10**((-50-rssi)/(10*3.5)))))


            #elif self.target_reached.is_set(): #only if we want to differentiate the feedback
                #led_color(0, 0, 1) #we need an actual red
                #await asyncio.sleep_ms(400)
                #led_off()
                #await asyncio.sleep_ms(400)

            else:
                # Ensure LED is OFF when not tracking
                led.off()
                rgb_off()
                await asyncio.sleep_ms(100)

    #tracks the previously found match given its address, exits when reaches timeout
    #target_rssi can be different and should be looked over
    async def search_with_scan(self, addr):

        self.connection_made_for_1.clear()      #clear the event for searching
        self.connection_made.clear()            #debugging prob?
        self.stop_advertising.clear()
        #self.target_reached.clear()            #clear the event for debugging

        self.search_is_going.set()    #OK to start the LED loop
        lights_loop = asyncio.create_task(self.distance_feedback_loop())
        
        print()
        print("Starting to track")
        print(f"this is the address it searches for: {addr}")
        print()

        start_time = time.time()

        #for exiting the loop on time
        SCAN_DURATION_MS = 1000

        try:
            while (time.time() - start_time) < self.timeout_s: #timeout is how long we want to keep trying
                #when the switch is on, find the device and track it, when done the loop is done.
                target_count = 0 
                retry_count = 0  # NEW (debugging)
                max_retries = 3  # NEW

                #print("entered the searching loop")

                #HARDWARE
                if not switch.value(): 
                    print("Switch off, exiting the tracking loop")
                    await asyncio.sleep(1)
                    break

                time_remaining = self.timeout_s - (time.time() - start_time)
                if time_remaining < (SCAN_DURATION_MS / 1000):
                    print("Not enough time for another scan")
                    break

                try:
                    #scan duration is 1 second now
                    async with aioble.scan(1000, interval_us, window_us, active=True) as scanner:
                        async for result in scanner:
                            if _BADGE_SERVICE_UUID in result.services():
                                
                                retry_count = 0
                                #print("entered the scanning loop")      #debugging
                                #print()

                                result_mac = self._extract_mac_address(result.device)
                                #print(result_mac)
                                
                                if result_mac == addr:

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

                                            print()
                                            print("************||************")
                                            print("Another connection made!!!")
                                            print("************||************")
                                            print()  
                                            rgb_off()
                                            led_set_color(7)

                                            print("Added to the set of already connected")
                                            self.already_connected.add(result.device)       #work with set
                                            
                                            #turn on the celebration lights
                                            #HARDWARE
                                            # await self.celebration_lights()

                                            #random delay
                                            await asyncio.sleep_ms(500)
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
                                    print()
                                    break

                except asyncio.CancelledError:
                    # Task was cancelled - clean up and exit
                    print("Tracking cancelled")
                    raise  # Re-raise so asyncio knows we're cancelled
                
                except OSError as e:
                    retry_count += 1  # NEW
                    if retry_count >= max_retries:  # NEW
                        print(f"Too many BLE errors ({max_retries}), giving up")
                        return False
                    print(f"Bluetooth error (attempt {retry_count}/{max_retries}): {e}")
                    await asyncio.sleep_ms(500)
                    continue
                
                except Exception as e:
                    retry_count += 1  # NEW
                    if retry_count >= max_retries:  # NEW
                        print(f"Too many errors ({max_retries}), giving up")
                        return False
                    print(f"Unexpected error (attempt {retry_count}/{max_retries}): {e}")
                    import sys
                    sys.print_exception(e)
                    await asyncio.sleep_ms(500)
                    continue  
        
        except asyncio.CancelledError:
            print("Tracking cancelled")
            raise
            
        except OSError as e:
            print(f"Bluetooth error: {e}, retrying...")
            await asyncio.sleep_ms(500)
            # Don't continue here - let finally cleanup happen
            
        except Exception as e:
            print(f"Unexpected error in scan loop: {e}")
            import sys
            sys.print_exception(e)
            await asyncio.sleep_ms(500)

        finally:
            # Always runs, even on return/exception
            lights_loop.cancel()
            try:
                await lights_loop
            except asyncio.CancelledError:
                pass
            self.search_is_going.clear()
            self.is_tracking = False
            self.current_rssi = None

        #if during the allowed time interval the match was not found-
        print("Proximity scanning time is over :(")
        return False           

    async def run_task(self):
        await self.setup_task()
        #advertises only if the switch is on
        #HARDWARE (fix this)
        advertise = asyncio.create_task(self.advertise())

        while True:

            #HARDWARE
            #if switch is not ON, wait 1 sec
            while not switch.value():
                print("Switch off: skipping scanning")
                await asyncio.sleep_ms(1000)

            #scans and listens interchangibly every 0.1s
            try:
                await self.find_other()
                await asyncio.sleep_ms(100)

            except Exception as e:
                print(f"Error from calling find_other(): {e}")

            if not (self.connection_made.is_set() or self.connection_made_for_1.is_set()):
                continue #try find_other again

            #now the connection is made, get the address and start tracking
            addr = self.get_address()
            if addr is None:
                #this is unlikely, but just for the debugging purposes, sure
                #would just lead back to the find_other
                print("You're stupid, it doesn't work like that ~>.<~")
                continue
            self.stop_advertising.clear()   #??? Excuse me ???
            
            #necessary delay, since the device needs to exit the connection state
            await asyncio.sleep_ms(1500)
            result = await self.search_with_scan(addr)
            count_of_tries = 0
            while not result and count_of_tries < 5:
                    
                #HARDWARE
                #check if the switch is still on
                if switch.value():
                    print("Try again")

                    result = await self.search_with_scan(addr)
                    count_of_tries += 1
                #else:
                    #break       #so right here, if the people didn't meet and switch is OFF it exits the loop

            #this is some weird delay
            #why if the cycle is completed or too many failed attempts, the device waits for 2 seconds?!?! 
            await asyncio.sleep_ms(200)


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
    badge = Badge([1, 2, 0], [1, 2, 0], 1, "AAAAA")
    await badge.run_task()

try: 
    asyncio.run(main())

except KeyboardInterrupt:
    turnOn.value(0)
    led_off()
    print("Program interrupted. LED turned off.")
