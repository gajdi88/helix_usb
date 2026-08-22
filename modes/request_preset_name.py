from modes.standard import Standard
import random
import threading
import logging

log = logging.getLogger(__name__)


class RequestPresetName(Standard):
    def __init__(self, helix_usb):
        Standard.__init__(self, helix_usb=helix_usb, name="request_preset_name")
        self.preset_name_data = []
        self.response_watch_dog_timer = None

    def start(self):
        log.info('Starting mode')
        self.preset_name_data = []
        preset_data_packet_double = self.helix_usb.preset_data_packet_double()
        data = [0x19, 0x0, 0x0, 0x18, 0x80, 0x10, 0xed, 0x3, 0x0, "XX", 0x0, 0x4, self.helix_usb.maybe_session_no, preset_data_packet_double[0], preset_data_packet_double[1], 0x0, 0x1, 0x0, 0x6,
                0x0, 0x9, 0x0, 0x0, 0x0, 0x83, 0x66, 0xcd, 0x4, 0x4, 0x64, 0x17, 0x65, 0xc0, 0x0, 0x0, 0x0]
        self.helix_usb.endpoint_0x1_out(data, silent=True)
        self.response_watch_dog_timer = threading.Timer(0.5, self.on_name_missing, [])
        self.response_watch_dog_timer.start()

    def shutdown(self):
        log.info('Shutting down mode')

    def on_name_missing(self):
        log.error('Didn''t receive current preset''s name. Ending mode ' + self.name + ' without success')
        self.helix_usb.switch_mode()

    @staticmethod
    def _extract_preset_name(data):
        """Preset name is tagged 0x6D followed by a length byte of
        0xA1 + len, then that many bytes of ASCII."""
        str_base = 0xa1
        for i in range(len(data) - 1):
            if data[i] == 0x6d and str_base < data[i + 1] < 0xc0:
                name_len = data[i + 1] - str_base
                raw = data[i + 2:i + 2 + name_len]
                if len(raw) == name_len and all(32 <= b <= 126 for b in raw):
                    return ''.join(chr(b) for b in raw)
        return ''

    def data_in(self, data_in):
        if self.helix_usb.check_keep_alive_response(data_in):
            return False  # don't print incoming message to console

        # 0x86 and the setlist byte are device/setlist specific on
        # Helix/LT, so both are wildcards here.
        elif self.helix_usb.my_byte_cmp(left=data_in[23:], right=[0x0, 0x83, 0x66, 0xcd, "XX", "XX", 0x67, 0x0, 0x68, "XX", 0x6b, 0xcd, 0x0, "XX", 0x6c, 0xcd], length=16):
            # self.helix_usb.log_data_in(data_in)
            for b in data_in[16:]:
                self.preset_name_data.append(b)

            if data_in[1] == 0x0:
                preset_name = self._extract_preset_name(self.preset_name_data)

                # log.info("*************************** Preset Name: " + preset_name)
                self.helix_usb.set_preset_name(preset_name)

                # update session no
                self.helix_usb.maybe_session_no = random.choice(range(0x04, 0xff))

                self.response_watch_dog_timer.cancel()
                self.response_watch_dog_timer = None

                self.helix_usb.switch_mode()

            return False   # don't print incoming message to console

        else:
            hex_str = ''.join('0x{:x}, '.format(x) for x in data_in)
            log.warning("Unexpected message in mode: " + str(hex_str))
            return True
