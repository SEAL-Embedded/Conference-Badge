
#check if the is_tracking is consistent in the code

#no switch version!

from machine import Pin
from utime import sleep
import bluetooth
import asyncio
import struct
import time

_BADGE_SERVICE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")

# How frequently to send advertising beacons.
_ADV_INTERVAL_MS = 250_000

#get the LED
#red = Pin(15, Pin.OUT)
#green = Pin(14, Pin.OUT)
#blue = Pin(13, Pin.OUT)
#turnOn = Pin(12, Pin.OUT)

#led = Pin("LED", Pin.OUT)

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

#switchScan = Pin(2, Pin.IN, Pin.PULL_DOWN)  # GP11 for scanning

''' legend for the "roles" (?):
degree = o if hs
degree = 1 if undergrad
degree = 2 if graduate'''

ble = bluetooth.BLE()
ble.active(True)

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
        self.badge_service = (_BADGE_SERVICE_UUID, (),)
        services = (self.badge_service,)
        handles = ble.gatts_register_services(services)
        print("The service is registered!")

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

    #not sure if we need this fuciton now that I changed everything 
    async def setup_task(self):
        await asyncio.sleep_ms(500)
        print(f"Badge {self.set_badgename} is set up.")
        print()
        await asyncio.sleep_ms(500)

    def ble_irq(event, data):
        if event == bluetooth._IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            if _BADGE_SERVICE_UUID in bluetooth.decode_services(adv_data):
                print("Found matching badge:", addr)
        elif event == bluetooth._IRQ_SCAN_DONE:
            print("Scan complete")
    
    ble.irq(ble_irq)
