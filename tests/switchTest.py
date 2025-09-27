from machine import Pin
import time

# Define LED pins (assuming common anode LED)
red = Pin(15, Pin.OUT)
green = Pin(14, Pin.OUT)
blue = Pin(13, Pin.OUT)
turnOn = Pin(12, Pin.OUT)  # You can remove this if not needed
switch = Pin(11, Pin.IN, Pin.PULL_DOWN)  # Button input with pull-down resistor
switchAdvertise = Pin(10, Pin.IN, Pin.PULL_DOWN)

while True:
    print("Switch state:", switch.value())
    print("Switch advertise state:", switchAdvertise.value())
