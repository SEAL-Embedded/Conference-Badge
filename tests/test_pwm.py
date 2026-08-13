
from machine import Pin, PWM
import time

turnOn = Pin(14, Pin.OUT)

# pins for the tracking (pwm) LED
r = PWM(Pin(12))
g = PWM(Pin(33))
b = PWM(Pin(32))

r.freq(1000)
g.freq(1000)
b.freq(1000)

#turns white and then waits for red
turnOn.value(1)
time.sleep(1)

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
#--- EDIT THE LED PWM RESPONCE HERE
def show_rssi_color(rssi, matched):
    if not matched: # Not matched → turn off (and in the main code should be "white") 
        rgb_off()
        return

    # Map RSSI from [-90 .. -40] → [0 .. 1]
    t = (rssi + 90) / 50 
    t = clamp(t)

    set_rgb(1 - t, t, 0)



rssi = -100
#test the object getting closer
while rssi < -50:
    show_rssi_color(rssi, True)
    time.sleep_ms(100)
    rssi += 1

print("done")

a = 50
rssi = -100

while rssi < -50:
    f = int(a*(10**((-50-rssi)/(10*3.5))))

    #on
    show_rssi_color(rssi, True)
    time.sleep_ms(f)

    #off
    rgb_off()
    time.sleep_ms(f)

    rssi += 4

#should really be just green
rgb_off()
