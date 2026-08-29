import sys
import select
import time
import machine

from pixel_colors import COLORS
from pixel_strip import PixelStrip


class PixelController:
    """Serial-driven controller for an addressable pixel strip on a Pico.

    Protocol (line-based over stdin/stdout):
      PING              -> PICO_READY        (handshake)
      BEAT              -> PICO_ALIVE
      CLOSE             -> PICO_CLOSED, then re-enters handshake
      INITSTRIP:pin:n   -> STRIP_INITIALIZED
      PIXEL:id:color:b  -> DONE
    Errors are reported as a single 'ERROR:...' line; the host should
    tolerate any unrecognised line rather than aborting.
    """

    def __init__(self, led_pin="LED", blink_interval_ms=500, loop_sleep_ms=1):
        self.onboard_led = machine.Pin(led_pin, machine.Pin.OUT)
        self.blink_interval_ms = blink_interval_ms
        self.loop_sleep_ms = loop_sleep_ms
        self.pixel_strip = None

        # Keyword -> handler. Dispatch replaces the sequential-if chain,
        # so control flow is explicit and CLOSE can't fall through.
        self._handlers = {
            "PING": self._handle_ping,
            "BEAT": self._handle_beat,
            "CLOSE": self._handle_close,
            "INITSTRIP": self._handle_initstrip,
            "PIXEL": self._handle_pixel,
        }

    # --- I/O helpers -----------------------------------------------------

    @staticmethod
    def _input_ready():
        return sys.stdin in select.select([sys.stdin], [], [], 0)[0]

    @staticmethod
    def _readline():
        return sys.stdin.readline().strip()

    # --- handshake -------------------------------------------------------

    def wait_for_handshake(self):
        """Block until the host sends PING, blinking the onboard LED."""
        last = time.ticks_ms()
        while True:
            if self._input_ready() and self._readline() == "PING":
                print("PICO_READY")
                self.onboard_led.off()
                return
            if time.ticks_diff(time.ticks_ms(), last) > self.blink_interval_ms:
                self.onboard_led.toggle()
                last = time.ticks_ms()
            time.sleep_ms(10)

    # --- command handling ------------------------------------------------

    def process_command(self, command):
        parts = command.split(":")
        handler = self._handlers.get(parts[0])
        if handler is None:
            print("ERROR:unknown_command:{}".format(parts[0]))
            return
        try:
            handler(parts)
        except (ValueError, IndexError) as exc:
            # Malformed command must not kill the loop mid-experiment.
            print("ERROR:bad_command:{}".format(exc))
                        

    def _handle_ping(self, parts):
        # PING during the main loop just re-acks; the actual handshake
        # gate lives in wait_for_handshake().
        print("PICO_READY")

    def _handle_beat(self, parts):
        print("PICO_ALIVE")

    def _handle_close(self, parts):
        print("PICO_CLOSED")
        self.wait_for_handshake()

    def _handle_initstrip(self, parts):
        # INITSTRIP:pin:num_pixels[:animate]
        #   e.g. INITSTRIP:28:4      -> with startup animation
        #        INITSTRIP:28:4:0    -> skip animation (no serial-deaf window)
        pin_num = int(parts[1])
        num_pixels = int(parts[2])
        animate = bool(int(parts[3])) if len(parts) > 3 else True
        self.pixel_strip = PixelStrip(pin_num, num_pixels, animate=animate)
        print("STRIP_INITIALIZED")

    def _handle_pixel(self, parts):
        # PIXEL:id:color:brightness  e.g. PIXEL:0:red:1
        if self.pixel_strip is None:
            print("ERROR:strip_not_initialized")
            return
        pixel_id = int(parts[1])
        color = parts[2]
        if color not in COLORS:
            print("ERROR:unknown_color:{}".format(color))
            return
        brightness = float(parts[3])
        pixel_color = self._apply_brightness(COLORS[color], brightness)
        self.pixel_strip.set_pixel(pixel_id, pixel_color)
        print("DONE")

    @staticmethod
    def _apply_brightness(color, brightness):
        r, g, b = color
        return (int(r * brightness), int(g * brightness), int(b * brightness))

    # --- main loop -------------------------------------------------------

    def run(self):
        self.wait_for_handshake()
        while True:
            if self._input_ready():
                line = self._readline()
                if line:
                    self.process_command(line)
            time.sleep_ms(self.loop_sleep_ms)


if __name__ == "__main__":
    PixelController().run()