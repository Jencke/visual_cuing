import time
import machine
import neopixel


time.sleep(2)

# Settings: Pin GP28, and let's assume you have 4 pixels (adjust if it's a ring or strip)
PIN_NUM = 28
NUM_PIXELS = 4

strip = neopixel.NeoPixel(machine.Pin(PIN_NUM), NUM_PIXELS)

colors = [
    (255, 0, 0),    # Red
    (0, 255, 0),    # Green
    (0, 0, 255),    # Blue
    (255, 255, 0),  # Yellow    
]

while True:
    for color in colors:
        for i in range(NUM_PIXELS):
            strip[i] = color            
            if i > 0:
                dim_color = tuple(int(c * 0.01) for c in color)  # Dim the previous pixel
                strip[i - 1] = dim_color
            strip.write()
            time.sleep(0.2)  # Wait for 1 second before changing to the next color
            if i == NUM_PIXELS - 1:
                # Dim the last pixel after the loop
                dim_color = tuple(int(c * 0.01) for c in color)
                strip[i] = dim_color
                strip.write()
                time.sleep(0.2)  # Wait for 1 second before changing to the next color
            
        