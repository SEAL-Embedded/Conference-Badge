
#last updated: 8/22

import bluetooth
import aioble
import asyncio
import struct
import urandom
import sys
import json
sys.stdout.buffer.write(b'') 


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

##---NECESSARY SETUPS---##
_BADGE_SERVICE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")

# Continuous scanning approach:
interval_us = 150000  # 150ms
window_us = 100000    # 100ms (scan 2/3 of the interval)

def count_bits(x):
    """Count how many switches are ON in a byte."""
    count = 0
    while x:
        count += x & 1
        x >>= 1
    return count

def encode_array(info_list):
    format_str = "<" + "B" * len(info_list)   # 'B' = unsigned byte, not 'b'
    return struct.pack(format_str, *[int(x) for x in info_list])

def decode_array(message):
    num_fields = len(message)
    format_str = "<" + "B" * num_fields
    return list(struct.unpack(format_str, message))

class Badge:
    #this creates fields for the Badge object, including the name, self_tags and service with characteristic
    def __init__(self, self_tags, search_tags, match_tolerance, name=None):

        #general settings
        self.timeout_s = 10

        self.number_of_elements = 10 #CHECK THIS? length of the info array 
        self.color_set = self.color() #CHECK THIS?

        #set info attributes
        self.set_badgename = name
        self.match_tolerance = match_tolerance
        self.set_info = self_tags
        self.set_target = search_tags
        self.adv_name = encode_array(self.set_info)
        self.adv_target = encode_array(self.set_target)

        #set and registed service 
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        aioble.register_services(self.badge_service)

        #event setup
        self.ready = asyncio.Event()
        self.connection_made_sca = asyncio.Event()          #if connection is made by scanning
        self.connection_made_adv = asyncio.Event()    #if connection is made by advertising
        #self.stop_advertising = asyncio.Event()         #if adv found connection, stop it
        self.search_is_going = asyncio.Event() 
        self.target_reached = asyncio.Event()           #if devices came to a close proximity
        self.is_tracking = False
        
        #debugging (if anything changes in manufacturer info this crashes so hard) 
        self.addr = None
        self.device_addr_adv = None
        self.device_addr_scan = None

    def color(self):
            x = (urandom.getrandbits(3) % 7) + 1
            #debugging
            print("This device's color is: ", x)
            return x

    def check_match_generic(self, tolerance, passed_array, passed_self):
        total_criteria = 0   # how many things I'm asking for
        total_matched = 0    # how many of those they actually have

        for i in range(self.number_of_elements):
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
        if not (self.check_match_generic(self.match_tolerance, read_info, self.set_target)):
            return False
        if not (self.check_match_generic(their_tolerance, read_target, self.set_info)):
            return False
        return True

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
            
    #For us to see how everything is set up, nothing really
    async def setup_task(self):
        print(f"Badge {self.set_badgename}")
        print(f"Badge's self: {self.set_info}, target: {self.set_target}")
        await asyncio.sleep_ms(500)

        print()
        print("if no white observed, fix!")
        print()

        await asyncio.sleep_ms(250)
        self.ready.set()

    async def find_other(self):
        
        # Get own MAC once before scanning
        own_mac = bluetooth.BLE().config('mac')[1]
        
        while True:
            await self.ready.wait()

            if self.connection_made_adv.is_set() or self.connection_made_sca.is_set():
                await asyncio.sleep_ms(250)
                print("find_other call\n")
                #print("Connection already made, waiting for the run task to move on")
                continue
         
            async with aioble.scan(1500, interval_us, window_us, active=True) as scanner:
                async for result in scanner:
                    if _BADGE_SERVICE_UUID in result.services(): #if its a badge

                            print(f"Found device: {result.name()} RSSI: {result.rssi} Address: {result.device}\n")
                            if (result.rssi < -100):
                                continue 

                            try:
                                #Get the generator + convert it to list
                                manufacturer_gen = result.manufacturer(0xFFFF)
                                manufacturer_list = list(manufacturer_gen)
                                
                                #debugging | Check if list is empty
                                if not manufacturer_list:
                                    print("Empty manufacturer list - no data for company ID 0xFFFF")
                                    continue

                                #The manufacturer data is likely the first (and probably only) item
                                manufacturer_data = bytes(manufacturer_list[0][1])
                                is_tracking = bool(manufacturer_data[0])
                                their_tolerance = int(manufacturer_data[1])
                                their_color = int(manufacturer_data[2])
                                print(f"is_tracking: {is_tracking}")
                                print(f"their match_tolerance: {their_tolerance} and color {their_color}")  # Debug print
                                print()

                                #debugging | if already tracks other device, don't distract it, try other device
                                if is_tracking:
                                    print("Device is in tracking mode, don't connect")
                                    print()
                                    continue
                                
                                info_byte_len = len(self.set_info)
                                target_byte_len = len(self.set_target)
                                
                                #Claude stuff that works
                                info_bytes = manufacturer_data[3:3 + info_byte_len]
                                target_bytes = manufacturer_data[3 + info_byte_len:3 + info_byte_len + target_byte_len]
                                
                                #somewhere here would go the color setting

                                #somewhere here would go the threshold match

                                read_info = decode_array(info_bytes)
                                read_target = decode_array(target_bytes)
                                print(f"their tags: {read_info}, they are looking for: {read_target}")

                            #debugging
                            except Exception as e:
                                print(f"Exception with the manufacturer info: {e}")
                                print()
                                continue

                            #if the match (on both sides!) is bad, don't do anything
                            if not self.check_match(read_info, read_target, their_tolerance):
                                continue
                            
                            else:
                                self.is_tracking = True #new thing
    #-------------------------- should flash something to indicate 
                                print("Found a good match on both sides! ")                            
                                #pulls up an address of the found device in the format that we like
                                self.device_addr_scan = self._extract_mac_address(result.device)
                                #self.device_addr_scan = str(result.device).split(', ')[1].rstrip(')')
                                
                                their_mac = bytes(result.device.addr)
                                if own_mac < their_mac:
                                    print("my color")
                                else:
                                    self.device_addr_scan = None
                                    self.is_tracking = False
                                    continue
                    
            print("No good devices nearby *or exited the scanning loop")

    #advertises all the time excluding the connection, this function shouldn't do anything besides advertising.
    async def advertise(self):
        while True:            
            await self.ready.wait()

            tracking = self.is_tracking #True/False
            tolerance = self.match_tolerance 
            color = self.color_set

            tracking_byte = struct.pack('B', int(tracking))
            tolerance_byte = struct.pack('B', tolerance)
            color_byte = struct.pack('B', color)

            #MANUFACTURER INFO IS NOT UPDATED IN THE LOOP
            manufacturer_data = tracking_byte + tolerance_byte + color_byte + self.adv_name + self.adv_target 

            #extra power drain when tracking for adversiting
            _ADV_INTERVAL_MS = 50_000 if (self.is_tracking) else 100_000

            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=self.set_badgename,
                services=[_BADGE_SERVICE_UUID],
                manufacturer=(0xFFFF, manufacturer_data),
                appearance=0,
            ) as connection: #???
                
                if self.is_tracking:
                    print("Already tracking, rejecting incoming connection")
                    await connection.disconnect()
                    continue

#-------------- should flash something to indicate? (for trials without switch)
                print("Advertising found connection!, from:", connection.device)
                print()

                self.connection_made_adv.set()
                self.is_tracking = True

                #formats the address of the conected device
                self.device_addr_adv = self._extract_mac_address(connection.device)

                await connection.disconnected(timeout_ms=None)
  
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
        else:
            return None

    


    #formula. good, but the constants can be different 
    def rssi_meters(self, rssi):
        return f"{10**((-50-rssi)/(10*3.5))}"
    
    async def run_task(self):
        await self.setup_task()
        #advertises only if the switch is on
        #HARDWARE (fix this)

        advertise_task = asyncio.create_task(self.advertise())
        find_other_task = asyncio.create_task(self.find_other())

        while True:

            #new thing
            while not (self.connection_made_sca.is_set() or self.connection_made_adv.is_set()):
                await asyncio.sleep_ms(100)

            #now the connection is made, get the address and start tracking
            addr = self.get_address()
            if addr is None:
                #this is unlikely, but just for the debugging purposes, sure
                #would just lead back to the find_other
                self.connection_made_sca.clear()
                self.connection_made_adv.clear()
                print("You're stupid, it doesn't work like that ~>.<~")
                continue
                
            #this is some weird delay
            #why if the cycle is completed or too many failed attempts, the device waits for 2 seconds?!?! 
            await asyncio.sleep_ms(200)

            # Reset match result for the next loop
            self.connection_made_sca.clear()
            self.connection_made_adv.clear()

        # Should never reach here, but if you add a stop condition:
        await advertise_task
        await find_other_task


async def main():
    self_tags, search_tags, match_tolerance, name = load_profile()
    badge = Badge(self_tags, search_tags, match_tolerance, name)
    await badge.run_task()

try: 
    asyncio.run(main())

except KeyboardInterrupt:
    print("Program interrupted. LED turned off.")
