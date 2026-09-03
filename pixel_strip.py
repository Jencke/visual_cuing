import neopixel
import machine
import time


class PixelStrip:
    """Thin wrapper over neopixel.NeoPixel with a decorative ready cue."""

    def __init__(self, pin_num, num_pixels, animate=True):
        self.strip = neopixel.NeoPixel(machine.Pin(pin_num), num_pixels)
        if animate:
            self._startup_animation()

    def _startup_animation(self, step_ms=200):
        # Decorative "device ready" cue: white sweep out, dark sweep back.
        # Blocking by design; the host receives STRIP_INITIALIZED only once
        # this completes, so ack and visual cue coincide.
        n = len(self.strip)
        for i in range(n):
            self.strip[i] = (255, 255, 255)
            self.strip.write()
            time.sleep_ms(step_ms)
        for i in range(n - 1, -1, -1):
            self.strip[i] = (0, 0, 0)
            self.strip.write()
            time.sleep_ms(step_ms)
    
    def set_pixel_buffered(self, index, color):
        if not 0 <= index < len(self.strip):
            raise IndexError("pixel index {} out of range".format(index))
        self.strip[index] = color
    
    def show(self):
        self.strip.write()
        
    def set_pixel(self, index, color):
        """Set a pixel color and immediately latch it to the strip."""
        self.set_pixel_buffered(index, color)
        self.show()
