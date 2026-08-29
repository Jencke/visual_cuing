import sys
import select
import time
import machine
from pixel_colors import COLORS
import neopixel

command_dict = {}

class PixelStrip:
    def __init__(self, pin_num, num_pixels):
        self.strip = neopixel.NeoPixel(machine.Pin(pin_num), num_pixels)
        self._init()  # Run the initial animation on startup
        
    def _init(self):
        # init animation: run_light from left to right, then right to left
        for i in range(len(self.strip)):
            self.strip[i] = (255, 255, 255)  # White
            self.strip.write()
            time.sleep(0.2)
        for i in range(len(self.strip)-1, -1, -1):
            self.strip[i] = (0, 0, 0)  # Off
            self.strip.write()
            time.sleep(0.2)
            
    def set_pixel(self, id, color):
        self.strip[id] = color
        self.strip.write()

def wait_for_handshake():
    onboard_led = machine.Pin("LED", machine.Pin.OUT)
    last_time = time.time()
    while True:
        if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            line = sys.stdin.readline().strip()            
            if line == "PING":
                print("PICO_READY")
                onboard_led.off()  # Turn off LED to indicate handshake complete
                break
        if time.time() - last_time > 0.5:
            # blink onboard LED to indicate waiting for handshake
            onboard_led.toggle()        
            last_time = time.time()                        
        time.sleep(0.01)

# Run handshake on boot
wait_for_handshake()

def apply_brightness(color, brightness):
    r, g, b = color
    return (int(r * brightness), int(g * brightness), int(b * brightness))

#PIXEL:0:red:1
def switch_pixel(command):
    global pixel_strip
    if not pixel_strip:
        print("Pixel strip not initialized")
        return
    command_parts = command.split(":")[1:]
    id = int(command_parts[0])
    color = command_parts[1]    
    if color not in COLORS:
        print(f"Unknown color: {color}")
        return
    brightness = float(command_parts[2])
    
    pixel_color = apply_brightness(COLORS[color], brightness)
    
    pixel_strip.set_pixel(id, pixel_color)
    print("DONE")
    

def process_command(command):
    if command == "CLOSE":
        print("PICO_CLOSED")
        wait_for_handshake()  # Wait for a new handshake after closing
    if command == "BEAT":
        print("PICO_ALIVE")
    if command.startswith("INITSTRIP"):
        # Example command: INITSTRIP:28:4
        parts = command.split(":")
        pin_num = int(parts[1])
        num_pixels = int(parts[2])
        global pixel_strip
        pixel_strip = PixelStrip(pin_num, num_pixels)
        print("STRIP_INITIALIZED")
    if command.startswith("PIXEL"):
        switch_pixel(command)

# --- Transition to your main operational loop ---
while True:
    # Main logic goes here
    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
        line = sys.stdin.readline().strip()
        if line:
            process_command(line)
    