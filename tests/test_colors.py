from machine import Pin
import time

#these are the breadboard pins
red1 = Pin(25, Pin.OUT)
green1 = Pin(26, Pin.OUT)
blue1 = Pin(27, Pin.OUT)
turnOn = Pin(14, Pin.OUT)

red = Pin(12, Pin.OUT)
green = Pin(33, Pin.OUT)
blue = Pin(32, Pin.OUT)
turnOn = Pin(14, Pin.OUT)


"""
these are the PCB pins

red1 = Pin(14, Pin.OUT)
green1 = Pin(12, Pin.OUT)
blue1 = Pin(27, Pin.OUT)

red = Pin(32, Pin.OUT)
green = Pin(33, Pin.OUT)
blue = Pin(25, Pin.OUT)

turnOn = Pin(26, Pin.OUT)
"""

print("Starting LED test...")
turnOn.value(1)

while True:
    print("RED")
    red.value(0)
    green.value(1)
    blue.value(1)
    time.sleep(1)

    red1.value(0)
    green1.value(1)
    blue1.value(1)
    time.sleep(1)
    
    print("GREEN")
    red.value(1)
    green.value(0)
    blue.value(1)
    time.sleep(1)
    
    red1.value(1)
    green1.value(0)
    blue1.value(1)
    time.sleep(1)

    print("BLUE")
    red.value(1)
    green.value(1)
    blue.value(0)
    time.sleep(1)

    red1.value(1)
    green1.value(1)
    blue1.value(0)
    time.sleep(1)
