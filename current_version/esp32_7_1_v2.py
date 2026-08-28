
#last updated: 8/24
#switch version!

from machine import Pin, PWM
import bluetooth
import aioble
import asyncio
import struct
import time
import urandom
import sys
import json
sys.stdout.buffer.write(b'') 

##---NECESSARY SETUPS---##
_BADGE_SERVICE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")
_ACK_NONE = b'\x00' * 3
_CANDIDATE_RSSI_THRESHOLD = -65   # ignore tag-matches farther than ~conversational distance
_SCAN_CYCLE_MS = 1000
ADV_REFRESH_S = 1       #how often to re-pack tracking/ack/color, since find_other() updates them live
_MAX_SEARCH_RETRIES = 25   #how many times run_task retries search_with_scan after a lock before giving up (was 5)

def short_id(mac_bytes):
    #Last 3 bytes of a MAC
    return bytes(mac_bytes[-3:])

def format_mac(addr_bytes):
    #Replaces _extract_mac_address for debug/print purposes (NAI-8).
    return ':'.join('{:02x}'.format(b) for b in addr_bytes)

#check if this function gets every color evenly
#CLAUDE: I can't give a real yes/no on "does this get every color evenly" without
#your actual badge MAC addresses (or the planned set) to test against
def pair_color(id_a, id_b):
    #Deterministic from both MAC-ids so both sides get the same color
    a, b = (id_a, id_b) if id_a < id_b else (id_b, id_a)
    h = 0
    for byte in (a + b):
        h = (h * 31 + byte) & 0xFF
    return (h % 7) + 1

# Continuous scanning approach:
interval_us = 150000  # 150ms
window_us = 100000    # 100ms (scan 2/3 of the interval)

#led = Pin(2, Pin.OUT) #on-board LED

#pins for the pair (static) LED
red = Pin(32, Pin.OUT)
green = Pin(33, Pin.OUT)
blue = Pin(25, Pin.OUT)
turnOn = Pin(26, Pin.OUT)

switch = Pin(13, Pin.IN, Pin.PULL_UP)  # switch 

#turn off the pair LED
def led_off():
    red.value(1)
    green.value(1)
    blue.value(1)

#given the color_code, change the pair LED color
def led_set_color(color_code):
    #colors are takes from bytes, hence this >> and &
    #000 thing and if one of the 0s is 1, they turn on this color
    r = (color_code >> 2) & 1
    g = (color_code >> 1) & 1
    b = color_code & 1
    
    red.value(0 if r else 1)
    green.value(0 if g else 1)
    blue.value(0 if b else 1)
    turnOn.value(1)
    print("This displayed color is: ", color_code)

# pins for the tracking (pwm) LED
r = PWM(Pin(14))
g = PWM(Pin(12))
b = PWM(Pin(27))

r.freq(1000)
g.freq(1000)
b.freq(1000)

#what does this do...
#turnOn.value(1)

# Given floats between 0.0 and 1.0, sets the color of the LEDs
def set_rgb(rr, gg, bb):
    # ESP32 PWM is 16-bit: 0–65535
    r.duty_u16(int((1-rr) * 65535))
    g.duty_u16(int((1-gg) * 65535))
    b.duty_u16(int((1-bb) * 65535))
    
# (PWM helper) Limit the possible values of the RGB 
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
    if not matched: # Not matched → (turn off and) full blue 
        rgb_off()
        return
    #Changes color as distance changes, should also be bright
    t = clamp((rssi + 90) / 50)
    set_rgb(1-t,t,0)    #blue is never there

def load_profile(filename = "profile.json"):
    try:
        with open(filename) as file:
            data = json.load(file)
        self_tags = data.get("self_tags", [0]*10)
        search_tags = data.get("search_tags", [0]*10)
        match_tolerance = data.get("match_tolerance", 1)
        name = data.get("name", "AAAAA")
        return self_tags, search_tags, match_tolerance, name
    except Exception as e:
        print(f"Failed to load profile, using defaults: {e}")
        return [0]*10, [0]*10, 1, "AAAAA"

def count_bits(x):
    """Count how many switches are ON in a byte."""
    count = 0
    while x:
        count += x & 1
        x >>= 1
    return count

#matching arrays (something that is got from the outside code)
def encode_array(info_list):
    format_str = "<" + "B" * len(info_list)   # 'B' = unsigned byte, not 'b'
    return struct.pack(format_str, *[int(x) for x in info_list])

def decode_array(message):
    num_fields = len(message)
    format_str = "<" + "B" * num_fields
    return list(struct.unpack(format_str, message))

class Badge:
    #this creates fields for the Badge object, including the name, info_array and service with characteristic
    def __init__(self, info_array, find_this, match_tolerance, name=None):

        #flat constants
        self.target_rssi = -48 #how close does one has to come
        self.timeout_s = 10    #for the tracking later

        #things we got from json gile =: info attributes
        self.set_badgename = name
        self.match_tolerance = match_tolerance
        self.self_tags = info_array
        self.search_tags = find_this
        self.adv_self = encode_array(self.self_tags)
        self.adv_search = encode_array(self.search_tags)

        #set and register service to make sure we don't connect to headphones 
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        aioble.register_services(self.badge_service)

        #new connection setups
        self.own_id = short_id(bluetooth.BLE().config('mac')[1])
        self.ack_target = _ACK_NONE     #the 3 last digits of the MAC address
        self.locked_addr = None         #the one chosen!

        #variables/fields that WILL be updated.
        self.current_rssi = None    #for the lights loop
        self.is_tracking = False    #supposed to help with not connecting while tracking
        self.already_connected = set()

        #debugging (if anything changes in manufacturer info this crashes so hard) 
        self.device_addr_scan = None
    
    async def celebration_lights(self):
        for i in range(21):
            led_set_color(i % 7 + 1)
            await asyncio.sleep_ms(300)
    
    #Used once, from setup_task(), to give the badge a default color before any match is found
    def color(self):
        x = (urandom.getrandbits(3) % 7) + 1
        #debugging
        print("This device's color is: ", x)
        return x

    def check_match_generic(self, tolerance, passed_array, passed_self):
            total_criteria = 0   # how many things I'm asking for
            total_matched = 0    # how many of those they actually have
    
            for i in range(10):
                if i in (0, 1, 2):
                    # degree/role/open — still single-value, not bitmask
                    if passed_self[i] == 0 or passed_array[i] == 0:
                        continue
                    total_criteria += 1
                    if passed_array[i] == passed_self[i]:
                        total_matched += 1
                else:
                    # bitmask categories
                    mine = passed_self[i]     # what I'm searching for, this category
                    theirs = passed_array[i]  # what they have, this category
    
                    if mine == 0:
                        continue  # I didn't ask for anything here, skip
    
                    overlap = mine & theirs
                    total_criteria += count_bits(mine)
                    total_matched += count_bits(overlap)
    
            if total_criteria == 0:
                print("No valid fields to compare!")
                return False
    
            return total_matched >= total_criteria - tolerance

    def check_match(self, read_info, read_target, their_tolerance):
        if not (self.check_match_generic(self.match_tolerance, read_info, self.self_tags)):
            return False
        if not (self.check_match_generic(their_tolerance, read_target, self.search_tags)):
            return False
        return True

    #For us to see how everything is set up, nothing really
    async def setup_task(self):
        print(f"Badge {self.set_badgename}")
        print(f"Badge's self: {self.self_tags}, target: {self.search_tags}")
        await asyncio.sleep_ms(500)

        #turn on white (all colors)
        led_set_color(7)
        rgb_off()

        print()
        print("if no white observed, fix!")
        print()

        #something that should be ran on the setup.
        self.color_set = self.color()

        await asyncio.sleep_ms(250)

    #tracking(1) + tolerance(1) + color(1) + ack(3) + info(10) + target(10) = 26 bytes exactly.
    async def find_other(self):
        
        #Get own MAC once before scanning
        #this could be used with the "new" pair color function
        own_mac = bluetooth.BLE().config('mac')[1]
        
        while True:
            if self.is_tracking:
                await asyncio.sleep_ms(300)  # already locked, nothing to evaluate
                continue

            while not switch.value():
                print("Switch off: skipping advertising")
                await asyncio.sleep_ms(1000)
                continue

            best_id = None
            best_rssi = -127
            reciprocated_device = None
            reciprocated_id = None
         
            async with aioble.scan(_SCAN_CYCLE_MS, interval_us, window_us, active=True) as scanner:
                async for result in scanner:
                    if _BADGE_SERVICE_UUID not in result.services(): #if its a badge
                        continue
                    if result.device in self.already_connected:
                        print("Already connected to this device once!")
                        print()
                        continue 
                    if result.rssi < -150:
                        continue

                    try:
                        #print(f"Found device: {result.name()} RSSI: {result.rssi} Address: {result.device}")
                        #print()

                        manufacturer_list = list(result.manufacturer(0xFFFF))
                        if not manufacturer_list:
                            continue
                        manufacturer_data = bytes(manufacturer_list[0][1])
                        #CLAUDE: per your "transmit everything except arrays" answer, a tracking-mode
                        #CLAUDE: badge now sends a SHORT 6-byte payload (tracking+tolerance+color+ack only,
                        #CLAUDE: no arrays) instead of the full 26 bytes. Please add a length check right here,
                        #CLAUDE: BEFORE decoding anything else:
                        #CLAUDE:     if len(manufacturer_data) < 26:
                        #CLAUDE:         continue  # busy/tracking badge, no arrays present, skip as candidate
                        #CLAUDE: Without this, the array-decode below will throw (struct.error, empty slice) on
                        #CLAUDE: every tracking-mode badge, every scan - caught by the except below so it won't
                        #CLAUDE: crash, but it'll spam "Exception with the manufacturer info" constantly for what
                        #CLAUDE: is actually normal behavior, not an error. Byte offsets 0-5 (tracking/tolerance/
                        #CLAUDE: color/ack) are identical in both the 6-byte and 26-byte forms, so everything
                        #CLAUDE: below this point that only reads bytes 0-5 doesn't need to change at all.
                        is_tracking = bool(manufacturer_data[0])
                        their_tolerance = int(manufacturer_data[1])

                        #we could just use this one instead of the pair_color function
                        their_color = int(manufacturer_data[2])

                        their_ack = manufacturer_data[3:6]

                        #print(f"is_tracking?: {is_tracking}")
                        #print(f"their match_tolerance: {their_tolerance} and color {their_color}")  # Debug print
                        #print()

                        info_byte_len = len(self.self_tags)     #these are supplementary
                        target_byte_len = len(self.search_tags) #to get the positions rigt

                        info_bytes = manufacturer_data[6:6 + info_byte_len]
                        target_bytes = manufacturer_data[6 + info_byte_len:6 + info_byte_len + target_byte_len]

                        read_info = decode_array(info_bytes)
                        read_target = decode_array(target_bytes)

                    except Exception as e:
                        print(f"Exception with the manufacturer info: {e}")
                        continue

                    if is_tracking:
                        continue  #they're already locked with someone else

                    if not self.check_match(read_info, read_target, their_tolerance):
                        continue

                    #print(f"their tags: {read_info}, they are looking for: {read_target}")

                    their_id = short_id(bytes(result.device.addr))

                    if result.rssi > best_rssi and result.rssi >= _CANDIDATE_RSSI_THRESHOLD:
                        best_rssi = result.rssi
                        best_id = their_id

                    if their_ack == self.own_id:
                        reciprocated_device = result.device     #check logic here, it makes sense, but a little confusing
                        reciprocated_id = their_id              #yes, if one found the other being a good match they should be automatically matched
                                                                #CLAUDE: replying to "check logic here" - my read: the lock a few lines down only
                                                                #CLAUDE: fires if the badge reciprocating me is ALSO my current best_id at the exact
                                                                #CLAUDE: moment its packet gets processed. best_id can still change later in the same
                                                                #CLAUDE: scan window, so whether a lock happens can depend on which order packets
                                                                #CLAUDE: arrive in - not wrong, but worth knowing it's order-sensitive within one window.
                                                                #CLAUDE: This is inside find_other so I'm not touching it - flagging for your review.

                    if reciprocated_id is not None and reciprocated_id == best_id:
                        self.locked_addr = reciprocated_id
                        #this reads result.device.addr's raw bytes directly, no string-parsing.
                        self.device_addr_scan = format_mac(bytes(reciprocated_device.addr))

                        #CLAUDE: replying to this - "smaller MAC defines the color" would need its own
                        #fairness check too 
                        self.color_set = pair_color(self.own_id, reciprocated_id)

                        self.ack_target = reciprocated_id

                        #This one has to be updated religiosly. PLEASE
                        self.is_tracking = True 
                        print("Mutual match locked with:", self.device_addr_scan, "/n")

                    else:
                        self.ack_target = best_id if best_id is not None else _ACK_NONE

                    await asyncio.sleep_ms(100)
                            
            #print("No good devices nearby *or exited the scanning loop")

    #advertises all the time excluding the connection, this function shouldn't do anything besides advertising.
    async def advertise(self):
        while True:  
            while not switch.value():
                print("Switch off: skipping advertising")
                await asyncio.sleep_ms(1000)
                continue

            #CLAUDE (NAI-3): manufacturer_data now comes from self._build_manufacturer_data() 
            manufacturer_data = self._build_manufacturer_data()

            #extra power drain when tracking for adversiting
            _ADV_INTERVAL_MS = 50_000 if (self.is_tracking) else 100_000

            #CLAUDE (NAI-4): check if hte timeout_ms has the needde function
            try: 
                await aioble.advertise(
                    _ADV_INTERVAL_MS,
                    name=self.set_badgename,
                    services=[_BADGE_SERVICE_UUID],
                    manufacturer=(0xFFFF, manufacturer_data),
                    appearance=0,
                    connectable=False,
                    timeout_ms=ADV_REFRESH_S * 1000,
                )
            except asyncio.TimeoutError:
                pass  #normal case: nobody connected, just refresh the payload and re-advertise

    #CLAUDE builds the manufacturer-data payload for whichever mode we're currently in.
    def _build_manufacturer_data(self):
        tracking_byte = struct.pack('B', int(self.is_tracking))
        tolerance_byte = struct.pack('B', self.match_tolerance)
        color_byte = struct.pack('B', self.color_set)
        header = tracking_byte + tolerance_byte + color_byte + self.ack_target

        if self.is_tracking:
            return header
        return header + self.adv_self + self.adv_search

    #formula. good, but the constants can be different 
    def rssi_meters(self, rssi):
        return f"{10**((-50-rssi)/(10*3.5))}"

    #based on the rssi, lights up different frequencies with the color chosen by the pair
    #CLAUDE (NAI-7): rewritten, fixed a fragility: the old code did a single check-then-break 
    async def distance_feedback_loop(self):
        while True:
            if not self.is_tracking:
                return  #tracking session ended (or never truly started) - nothing more to do

            if self.current_rssi is not None:
                rssi = self.current_rssi

                #HARDWARE 
                a = 100
                #Adjust blink rate based on signal strength
                led_set_color(self.color_set)
                print(self.color_set)

                show_rssi_color(self.current_rssi, self.is_tracking)
                blink_ms = int(a * float(self.rssi_meters(rssi)))
                await asyncio.sleep_ms(blink_ms)
                rgb_off()
                await asyncio.sleep_ms(blink_ms)

            else:
                # Ensure LED is OFF when not tracking
                rgb_off()
                await asyncio.sleep_ms(100)

    #tracks the previously found match given its address, exits when reaches timeout
    #target_rssi can be different and should be looked over
    #CLAUDE (NAI-6): rewritten - identity check now uses short_id(bytes(result.device.addr)) == add
    async def search_with_scan(self, addr):

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
                                
                                #print("entered the scanning loop")      #debugging
                                print()

                                if short_id(bytes(result.device.addr)) == addr:

                                    self.current_rssi = result.rssi     #both start
                                    self.is_tracking = True             #the LED loop and protection from connection

                                    print(f"Found targeted device! RSSI: {self.current_rssi}")                            
                                    
                                    #if reached target
                                    if self.current_rssi > self.target_rssi:

                                        print("Target reached!")
                                        target_count += 1

                                        #wait before trying again 
                                        await asyncio.sleep_ms(100)

                                        #returns true
                                        if target_count >= 2:   #just to make sure they met
                                            self.is_tracking = False
                                            self.current_rssi = None

                                            # Wait for LED loop to see the cleared flag
                                            await asyncio.sleep_ms(100)

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
                                            await self.celebration_lights()

                                            led_off(); rgb_off() #both LEDs off

                                            #random delay
                                            await asyncio.sleep_ms(500)

                                            #IF THE SWITCH IS ON:
                                            self.is_tracking = False #so it is discoverable

                                            return True
                                        
                                        #if this is the first encounter, continue
                                        else:
                                            print()
                                            continue

                                    #if devices aren't close enough, restart the count
                                    else:
                                        target_count = 0

                                                                        
                                    #links to the function that gives a distance from the rssi
                                    distance = self.rssi_meters(self.current_rssi)
                                    print(f"Approximated distance: {distance}m")

                                    await asyncio.sleep_ms(500) 
                                    print()

                                    #this is to exit the scanning loop and start scanning again
                                    print()
                                    continue

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
            self.is_tracking = False
            self.current_rssi = None

        #if during the allowed time interval the match was not found-
        print("Proximity scanning time is over :(")
        return False           

    #CLAUDE (NAI-5): rewritten. connection_made_sca/connection_made_adv (removed, NAI-1) replaced with
    #CLAUDE: polling self.is_tracking directly
    #HARDWARE (fix this)
    async def run_task(self):
        await self.setup_task()
        #advertises only if the switch is on
        advertise_task = asyncio.create_task(self.advertise())
        find_other_task = asyncio.create_task(self.find_other())

        while True:

            #HARDWARE
            #if switch is not ON, wait 1 sec
            while not switch.value():
                print("Switch off: skipping scanning")
                await asyncio.sleep_ms(500)

            while not self.is_tracking:
                await asyncio.sleep_ms(100)

            #now the connection is made, get the address and start tracking
            addr = self.locked_addr
            
            while not switch.value():
                print("Switch off: skipping scanning")
                await asyncio.sleep_ms(500)
                
            #UNnecessary delay, since the device needs to exit the connection state
            await asyncio.sleep_ms(1500)
            result = await self.search_with_scan(addr)
            count_of_tries = 0
            while not result and count_of_tries < _MAX_SEARCH_RETRIES:
                #HARDWARE
                #check if the switch is still on
                if switch.value():
                    print("Try again")
                    result = await self.search_with_scan(addr)
                    count_of_tries += 1
                else:
                    break       #so right here, if the people didn't meet and switch is OFF it exits the loop

            #200ms pause before returning to wait for the next lock
            await asyncio.sleep_ms(200)

            #program should not exit the serching loop until found the device. 
            #If the user wants to give up on finding this exact match, they can turn off/on(if from advertising) 
            #the searching switch and turn it back on/off again to start over

            #this is the end of the loop^ 

            # Reset match result for the next loop
            self.locked_addr = None

#somewhat updated
async def main():
    self_tags, search_tags, match_tolerance, name = load_profile()
    badge = Badge(self_tags, search_tags, match_tolerance, name)
    await badge.run_task()

try: 
    asyncio.run(main())

except KeyboardInterrupt:
    turnOn.value(0)
    led_off()
    print("Program interrupted. LED turned off.")