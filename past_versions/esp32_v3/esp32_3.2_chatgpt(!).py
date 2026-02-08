from machine import Pin
import bluetooth
import aioble
import asyncio
import struct
import time
import sys

sys.stdout.buffer.write(b'')

# ---------------- BLE UUIDs ----------------
_BADGE_SERVICE_UUID = bluetooth.UUID("6a94195c-98ff-4f26-9140-bc341ca1a88c")
_INFO_CHAR_UUID = bluetooth.UUID("aa01b013-dcea-4880-9d89-a47e76c69c3c")
_MATCH_CHAR_UUID = bluetooth.UUID("2aca7f5b-02b7-4232-a5f0-56cb9155be7a")

_ADV_INTERVAL_MS = 250_000

# ---------------- LED PINS ----------------
red = Pin(25, Pin.OUT)
green = Pin(26, Pin.OUT)
turnOn = Pin(14, Pin.OUT)
led = Pin(2, Pin.OUT)

# ---------------- LED HELPERS ----------------
def led_off():
    red.value(1)
    green.value(1)
    turnOn.value(0)
    led.value(0)

def led_green():
    red.value(1)
    green.value(0)
    turnOn.value(1)
    led.value(1)

def led_red():
    red.value(0)
    green.value(1)
    turnOn.value(1)
    led.value(1)

# ---------------- ENCODE / DECODE ----------------
def encode_array(info_list):
    fmt = "<" + "b" * len(info_list)
    return struct.pack(fmt, *[int(x) for x in info_list])

def decode_array(message):
    fmt = "<" + "b" * len(message)
    return list(struct.unpack(fmt, message))

# ================= BADGE CLASS =================
class Badge:

    def __init__(self, info_array, find_this, match_tolerance, name=None):

        self.set_badgename = name
        self.match_tolerance = match_tolerance
        self.number_of_elements = 10

        self.is_tracking = False
        self.current_rssi = None
        self.target_rssi = -48
        self.timeout_s = 10

        self.set_info = self._pad_array(info_array)
        self.set_target = self._pad_array(find_this)

        self.adv_name = encode_array(self.set_info)
        self.adv_target = encode_array(self.set_target)

        # BLE
        self.badge_service = aioble.Service(_BADGE_SERVICE_UUID)
        self.info_characteristic = aioble.Characteristic(
            self.badge_service, _INFO_CHAR_UUID, read=True, notify=True
        )
        self.match_characteristic = aioble.Characteristic(
            self.badge_service, _MATCH_CHAR_UUID, read=True, write=True
        )
        aioble.register_services(self.badge_service)

        # State
        self.already_connected = set()
        self.connection_made = asyncio.Event()
        self.connection_made_for_1 = asyncio.Event()
        self.stop_advertising = asyncio.Event()
        self.search_is_going = asyncio.Event()
        self.target_reached = asyncio.Event()

        self.device_addr_scan = None
        self.device_addr_adv = None

    # ---------------- HELPERS ----------------
    def _pad_array(self, arr):
        return (arr + [-1] * self.number_of_elements)[:self.number_of_elements]

    def _extract_mac_address(self, device):
        try:
            return str(device).split(", ")[1].rstrip(")")
        except Exception:
            return None

    # ---------------- MATCH LOGIC ----------------
    def check_match(self, read_info):
        match = compared = 0
        for i in range(self.number_of_elements):
            if self.set_target[i] == -1 or read_info[i] == -1:
                continue
            compared += 1
            if read_info[i] == self.set_target[i]:
                match += 1

        if compared == 0:
            return False

        result = match >= compared - self.match_tolerance
        print("MATCH" if result else "NO MATCH")
        return result

    def check_IAM_match(self, read_target, their_tolerance):
        match = compared = 0
        for i in range(self.number_of_elements):
            if self.set_info[i] == -1 or read_target[i] == -1:
                continue
            compared += 1
            if read_target[i] == self.set_info[i]:
                match += 1

        if compared == 0:
            return False

        return match >= compared - their_tolerance

    # ---------------- FIND OTHER ----------------
    async def find_other(self):
        async with aioble.scan(1000, active=True) as scanner:
            async for result in scanner:
                if _BADGE_SERVICE_UUID not in result.services():
                    continue

                if result.rssi < -100:
                    continue

                manufacturer_list = list(result.manufacturer(0xFFFF))
                if not manufacturer_list:
                    continue

                data = bytes(manufacturer_list[0][1])
                is_tracking = bool(data[0])
                their_tolerance = data[1]

                if is_tracking:
                    continue

                info_len = len(self.set_info)
                tgt_len = len(self.set_target)

                read_info = decode_array(data[2:2 + info_len])
                read_target = decode_array(data[2 + info_len:2 + info_len + tgt_len])

                if not self.check_match(read_info):
                    led_red()
                    continue

                if not self.check_IAM_match(read_target, their_tolerance):
                    led_red()
                    continue

                # GOOD MATCH
                led_green()
                self.device_addr_scan = self._extract_mac_address(result.device)
                self.connection_made.set()
                return True

        return None

    # ---------------- ADVERTISE ----------------
    async def advertise(self):
        while True:
            if self.stop_advertising.is_set():
                await asyncio.sleep_ms(200)
                continue

            payload = (
                struct.pack("B", int(self.is_tracking)) +
                struct.pack("B", self.match_tolerance) +
                self.adv_name +
                self.adv_target
            )

            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=self.set_badgename,
                services=[_BADGE_SERVICE_UUID],
                manufacturer=(0xFFFF, payload),
            ) as connection:

                self.connection_made_for_1.set()
                self.device_addr_adv = self._extract_mac_address(connection.device)
                await connection.disconnected()
                self.stop_advertising.set()

    # ---------------- TRACKING ----------------
    async def distance_feedback_loop(self):
        while self.search_is_going.is_set():
            if self.is_tracking and self.current_rssi is not None:
                led_green()
                await asyncio.sleep_ms(200)
                led_off()
                await asyncio.sleep_ms(200)
            else:
                led_off()
                await asyncio.sleep_ms(100)

    async def search_with_scan(self, addr):
        self.search_is_going.set()
        lights = asyncio.create_task(self.distance_feedback_loop())

        start = time.time()
        while time.time() - start < self.timeout_s:
            async with aioble.scan(2000, active=True) as scanner:
                async for result in scanner:
                    if self._extract_mac_address(result.device) != addr:
                        continue

                    self.current_rssi = result.rssi
                    self.is_tracking = True

                    if self.current_rssi > self.target_rssi:
                        self.search_is_going.clear()
                        lights.cancel()
                        await self.celebration_lights()
                        self.is_tracking = False
                        return True

        lights.cancel()
        self.is_tracking = False
        return False

    async def celebration_lights(self):
        led_green()
        await asyncio.sleep_ms(2000)
        led_off()

    # ---------------- MAIN LOOP ----------------
    async def run_task(self):
        adv = asyncio.create_task(self.advertise())

        while True:
            await self.find_other()

            if not (self.connection_made.is_set() or self.connection_made_for_1.is_set()):
                continue

            addr = self.device_addr_scan or self.device_addr_adv
            self.stop_advertising.clear()
            await asyncio.sleep_ms(1500)
            await self.search_with_scan(addr)

            self.connection_made.clear()
            self.connection_made_for_1.clear()

        await adv

# ================= MAIN =================
async def main():
    badge = Badge([1, 2, 0], [1, 2, 0], 1, "AAAAA")
    await badge.run_task()

try:
    asyncio.run(main())
except KeyboardInterrupt:
    led_off()
    print("Program interrupted.")
