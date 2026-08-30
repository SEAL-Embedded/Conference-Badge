
#last updated: 8/30
#this is for the ble check only
#the only thing we really want to have is the advertising and scanning 

import bluetooth
import aioble
import asyncio
import time
import sys
sys.stdout.buffer.write(b'') 

##---NECESSARY SETUPS---##
_BADGE_SERVICE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")
_ADV_INTERVAL_MS = 50_000           #two tests: one with this = 100_000 and another with this = 50_000
ADV_REFRESH_S = 1                   #how often to re-pack tracking/ack/color, since find_other() updates them live
_MAX_SEARCH_RETRIES = 5             #how many times search_with_scan is ran after a lock before giving up 
interval_us = 150000                #150ms
window_us = 100000                  #100ms (scan 2/3 of the interval)

def short_id(mac_bytes):
    #Last 3 bytes of a MAC
    return bytes(mac_bytes[-3:])

def format_mac(addr_bytes):
    #Replaces _extract_mac_address for debug/print purposes (NAI-8).
    return ':'.join('{:02x}'.format(b) for b in addr_bytes)

class Badge:
    #this creates fields for the Badge object, including the name, info_array and service with characteristic
    def __init__(self, info_array, find_this, match_tolerance, name=None):

        #flat constants
        self.target_rssi = -48 #how close does one has to come
        self.timeout_s = 10    #for the tracking later
        self.set_badgename = name

        #set and register service to make sure we don't connect to headphones 
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        aioble.register_services(self.badge_service)

        #new connection setups
        self.own_id = short_id(bluetooth.BLE().config('mac')[1])

        #self.ack_target = _ACK_NONE     #the 3 last digits of the MAC address
        self.locked_addr = None         #the one chosen!
        
        #variables/fields that WILL be updated.
        self.current_rssi = None    #for the lights loop
        self.is_tracking = False    #supposed to help with not connecting while tracking
        self.already_connected = set()

        #debugging (if anything changes in manufacturer info this crashes so hard) 
        self.device_addr_scan = None
    
    #For us to see how everything is set up, nothing really
    async def setup_task(self):
        print(f"Badge {self.set_badgename}")
        await asyncio.sleep_ms(500)

        await asyncio.sleep_ms(250)

    #advertises all the time excluding the connection, this function shouldn't do anything besides advertising.
    async def advertise(self):
        while True:  
            try: 
                await aioble.advertise(
                    _ADV_INTERVAL_MS,
                    name=self.set_badgename,
                    services=[_BADGE_SERVICE_UUID],
                    appearance=0,
                    connectable=False,
                    timeout_ms=ADV_REFRESH_S * 1000,
                )
            except asyncio.TimeoutError:
                pass  #normal case: nobody connected, just refresh the payload and re-advertise

    #formula. good, but the constants can be different 
    def rssi_meters(self, rssi):
        return f"{10**((-50-rssi)/(10*3.5))}"

    #tracks the previously found match given its address, exits when reaches timeout
    #target_rssi can be different and should be looked over
    #CLAUDE (NAI-6): rewritten - identity check now uses short_id(bytes(result.device.addr)) == add
    async def search_with_scan(self, addr):

        print()
        print(f"Tracking: this is the address it searches for: {addr}")
        print()

        start_time = time.time()

        #for exiting the loop on time
        SCAN_DURATION_MS = 1000

        try:
            while (time.time() - start_time) < self.timeout_s: #timeout is how long we want to keep trying
                #print("entered the searching loop")

                time_remaining = self.timeout_s - (time.time() - start_time)
                if time_remaining < (SCAN_DURATION_MS / 1000):
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

                                    print(f"Found targeted device! RSSI: {self.current_rssi}")                                                        
                                    #links to the function that gives a distance from the rssi
                                    distance = self.rssi_meters(self.current_rssi)
                                    print(f"Approximated distance: {distance}m")

                                    await asyncio.sleep_ms(500) 
                                    #this is to exit the scanning loop and start scanning again
                                    print()
                                    continue

                except asyncio.CancelledError:
                    # Task was cancelled - clean up and exit
                    print("Tracking cancelled")
                    raise  # Re-raise so asyncio knows we're cancelled 
        
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

        while True:

            #now the connection is made, get the address and start tracking
            addr = self.locked_addr

            result = await self.search_with_scan(addr)
            count_of_tries = 0
            while not result and count_of_tries < _MAX_SEARCH_RETRIES:
                print("Try again")
                result = await self.search_with_scan(addr)
                count_of_tries += 1
            else:
                break       

            #200ms pause before returning to wait for the next lock
            await asyncio.sleep_ms(200)

            # Reset match result for the next loop
            self.locked_addr = None

#somewhat updated
async def main():
    badge = Badge(None, None, None, "Badge1")
    await badge.run_task()

try: 
    asyncio.run(main())

except KeyboardInterrupt:
    print("Program interrupted. LED turned off.")
