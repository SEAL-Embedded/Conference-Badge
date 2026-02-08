# This code implements a PWM LED function, creating a variable brightness/color that shifts smoothly over time. 
# This assumes a common anode LED with three input pins and a turn on pin
from machine import Pin, PWM
import bluetooth
import aioble
import asyncio
import struct
import time
import sys

r = PWM(Pin(25))
g = PWM(Pin(26))
b = PWM(Pin(27))
turnOn = Pin(14, Pin.OUT)
led = Pin(2, Pin.OUT)

r.freq(1000)
g.freq(1000)
b.freq(1000)

turnOn.value(1)

# Given floats between 0.0 and 1.0, sets the color of the LEDs
def set_rgb(rr, gg, bb):
    # ESP32 PWM is 16-bit: 0–65535
    r.duty_u16(int((1-rr) * 65535))
    g.duty_u16(int((1-gg) * 65535))
    b.duty_u16(int((1-bb) * 65535))
    
# Limits the possible values of the RGB 
def clamp(x, lo=0.0, hi=1.0):
    if x < lo: return lo
    if x > hi: return hi
    return x

# Given an RSSI value, maps it to a float that represents its color and brightness
def show_rssi_color(rssi):
    # Map RSSI from [-90 .. -40] → [0 .. 1]
    t = (rssi + 90) / 50
    t = clamp(t)

    # Color gradient:
    # Far = Blue
    # Mid = Yellow
    # Near = Red

    if t < 0.5:
        # Blue → Yellow
        k = t / 0.5
        r_col = k
        g_col = k
        b_col = 1 - k
    else:
        # Yellow → Red
        k = (t - 0.5) / 0.5
        r_col = 1
        g_col = 1 - k
        b_col = 0

    # Brightness also increases as you get closer
    brightness = 0.2 + 0.8 * t

    set_rgb(r_col * brightness, g_col * brightness, b_col * brightness)

# Test code
for rssi in range(-90, -39, 1):   # -90 → -40
    show_rssi_color(rssi)
    print(rssi)
    led.value(0)
    time.sleep(0.4)
    led.value(1)


