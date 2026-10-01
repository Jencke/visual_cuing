import sys
import select
import time
import machine

from pixel_colors import COLORS
from pixel_strip import PixelStrip

class ScheduledEvent:
    def __init__(self, pixel_id, time_us, color, brightness):
        self.pixel_id = pixel_id
        self.time_us = time_us
        self.color = color  # (r, g, b), resolved when the command arrives
        self.brightness = brightness



class MonotonicMicros:
    """Non-wrapping 64-bit microsecond counter built on time.ticks_us().

    ticks_us() itself wraps at the port's TICKS_PERIOD (~17.9 min on RP2).
    This accumulates ticks_diff() deltas into a Python big-int, so the value
    never wraps in any practical timescale while keeping 1 us resolution.

    CONTRACT: read() must be called at least once per ~8 min (half the wrap
    period) or a wrap is missed and time is silently lost. The controller's
    main loop calls it every iteration, so the only risk is a handler that
    blocks longer than that without reading -- a future scheduler's long
    wait loop must therefore call read() (or ticks_diff) as it spins.

    Not thread-safe: read() mutates state and must be called from one thread.
    """

    def __init__(self):
        self._last = time.ticks_us()
        self._acc = 0

    def read(self):
        now = time.ticks_us()
        self._acc += time.ticks_diff(now, self._last)
        self._last = now
        return self._acc


class PixelController:
    """Serial-driven controller for an addressable pixel strip on a Pico.

    Protocol (line-based over stdin/stdout):
      PING              -> PICO_READY        (handshake)
      BEAT              -> PICO_ALIVE
      CLOSE             -> PICO_CLOSED, then re-enters handshake
      INITSTRIP:pin:n   -> STRIP_INITIALIZED
      PIXEL:id:color:b  -> DONE
      SCHEDULE:t_us:id:color:b[:dur_us] -> SCHEDULED
      SYNC              -> PICO_TIME:<us>     (non-wrapping 64-bit microseconds)
    color is a name from pixel_colors.COLORS or 'r,g,b' with values 0-255.
    Errors are reported as a single 'ERROR:...' line; the host should
    tolerate any unrecognised line rather than aborting.
    """

    def __init__(self, led_pin="LED", blink_interval_ms=500, loop_sleep_ms=1):
        self.onboard_led = machine.Pin(led_pin, machine.Pin.OUT)
        self.blink_interval_ms = blink_interval_ms
        self.loop_sleep_ms = loop_sleep_ms
        self.pixel_strip = None
        self._clock64 = MonotonicMicros()
        self._scheduled_events = []  # List of ScheduledEvent, sorted by time_us
        self.coalesce_window_us = 50  # Time window to coalesce events before execution
        self._frame_latch_offset_us = 0

        # Keyword -> handler. Dispatch replaces the sequential-if chain,
        # so control flow is explicit and CLOSE can't fall through.
        self._handlers = {
            "PING": self._handle_ping,
            "BEAT": self._handle_beat,
            "CLOSE": self._handle_close,
            "INITSTRIP": self._handle_initstrip,
            "PIXEL": self._handle_pixel,
            "SYNC": self._handle_sync,
            "SCHEDULE": self._handle_schedule,
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
        """Block until the host sends PING, blinking the onboard LED.

        Uses ticks_ms/ticks_diff: time.time() has 1 s resolution on the
        RP2040, so the sub-second blink interval would otherwise not work.
        """
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

    def _handle_sync(self, parts):
        # Capture Pico time as early as possible, before formatting/printing,
        # so reply-path latency does not bias the timestamp. The value is a
        # non-wrapping 64-bit microsecond count, so the host needs no modular
        # arithmetic and the scheduler can compare deadlines with plain >=.
        t = self._clock64.read()
        print("PICO_TIME:{}".format(t))

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

    @staticmethod
    def _parse_color(text):
        """Color name or 'r,g,b' (0-255) -> (r, g, b), or None if invalid."""
        if text in COLORS:
            return COLORS[text]
        try:
            rgb = tuple(int(c) for c in text.split(","))
        except ValueError:
            return None
        if len(rgb) != 3 or not all(0 <= c <= 255 for c in rgb):
            return None
        return rgb

    def _handle_schedule(self, parts):
        # SCHEDULE:time_us:id:color:brightness[:duration_us]
        #   e.g. SCHEDULE:1000000:0:red:1  or  SCHEDULE:1000000:0:255,0,0:1:100000
        time_us = int(parts[1])
        pixel_id = int(parts[2])
        color = self._parse_color(parts[3])
        if color is None:
            print("ERROR:unknown_color:{}".format(parts[3]))
            return
        brightness = float(parts[4])
        event = ScheduledEvent(pixel_id, time_us, color, brightness)
        self._scheduled_events.append(event)
        self._scheduled_events.sort(key=lambda e: e.time_us)
        
        if len(parts) > 5:
            t_pixel_off = int(parts[5]) + time_us
            event_off = ScheduledEvent(pixel_id, t_pixel_off, (0, 0, 0), 0)
            self._scheduled_events.append(event_off)
            self._scheduled_events.sort(key=lambda e: e.time_us)
        print("SCHEDULED")
            

    def _handle_pixel(self, parts):
        # PIXEL:id:color:brightness  e.g. PIXEL:0:red:1  or  PIXEL:0:255,0,0:1
        if self.pixel_strip is None:
            print("ERROR:strip_not_initialized")
            return
        pixel_id = int(parts[1])
        color = self._parse_color(parts[2])
        if color is None:
            print("ERROR:unknown_color:{}".format(parts[2]))
            return
        brightness = float(parts[3])
        pixel_color = self._apply_brightness(color, brightness)
        self.pixel_strip.set_pixel(pixel_id, pixel_color)
        print("DONE")

    @staticmethod
    def _apply_brightness(color, brightness):
        r, g, b = color
        return (int(r * brightness), int(g * brightness), int(b * brightness))

    # --- main loop -------------------------------------------------------

    def _handle_scheduled_event(self, events):
        """Fire a coalesced batch of ScheduledEvents in one frame.

        events[0].time_us is the earliest requested visible-onset time in
        this batch (run() already grouped everything else in it to within
        coalesce_window_us of that). The underlying write() must START
        frame_latch_offset_us before that time, since WS2812/SK6812 only
        latches the new colors once the full frame has shifted out and the
        reset gap is seen -- see the note on SET_LATCH_OFFSET.
        """
        if self.pixel_strip is None:
            return
        target_us = events[0].time_us - self._frame_latch_offset_us

        for event in events:
            pixel_color = self._apply_brightness(event.color, event.brightness)
            self.pixel_strip.set_pixel_buffered(event.pixel_id, pixel_color)


        while self._clock64.read() < target_us:
            pass

        self.pixel_strip.show()  # blocking; latch happens when this returns
    
    def run(self):
        self.wait_for_handshake()
        while True:
            # Advance the 64-bit clock every iteration so it can never miss a
            # ticks_us() wrap while the loop is alive.
            now = self._clock64.read()
            if self._input_ready():
                line = self._readline()
                if line:
                    self.process_command(line)
            if self._scheduled_events:
                time_to_next_event = self._scheduled_events[0].time_us - now
                if time_to_next_event <= 3000: # 3 ms before the next event jump into the handler                    
                    events = [self._scheduled_events.pop(0)]
                    while len(self._scheduled_events) > 0 and self._scheduled_events[0].time_us - events[0].time_us <= self.coalesce_window_us:
                        events.append(self._scheduled_events.pop(0))                    
                    self._handle_scheduled_event(events)
            time.sleep_ms(self.loop_sleep_ms)


if __name__ == "__main__":
    PixelController().run()