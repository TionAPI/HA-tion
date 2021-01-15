import logging
import time
from typing import List
from time import localtime, strftime

from bluepy import btle
from bluepy.btle import DefaultDelegate

_LOGGER = logging.getLogger(__name__)


class TionException(Exception):
    def __init__(self, expression, message):
        self.expression = expression
        self.message = message


class TionDelegation(DefaultDelegate):
    def __init__(self):
        self._data: List = []
        self.__topic = None
        DefaultDelegate.__init__(self)

    def handleNotification(self, handle: int, data: bytes):
        self._data.append(data)
        _LOGGER.debug("Got data in %d response %s", handle, bytes(data).hex())
        self.__topic.read()

    def setReadTopic(self, topic):
        self.__topic = topic

    @property
    def data(self) -> bytes:
        return self._data.pop(0)

    @property
    def haveNewData(self) -> bool:
        return len(self._data) > 0


class TionTest:
    statuses = ['off', 'on']
    modes = ['recirculation', 'mixed']  # 'recirculation', 'mixed' and 'outside', as Index exception
    uuid_notify: str = ""
    uuid_write: str = ""

    command_prefix = 61  # 0x3d
    command_suffix = 90

    command_PAIR = 5
    command_REQUEST_PARAMS = 1
    command_SET_PARAMS = 2

    def __init__(self, mac: str):
        self._mac = mac
        self._btle: btle.Peripheral = btle.Peripheral(None)
        self._delegation = TionDelegation()
        self._fan_speed = 0
        self._model: str = self.__class__.__name__
        self._data: bytearray = bytearray()
        """Data from breezer response at request state command"""
        # states
        self._in_temp: int = 0
        self._out_temp: int = 0
        self._target_temp: int = 0
        self._fan_speed: int = 0
        self._mode: int = 0
        self._state: bool = False
        self._heater: bool = False
        self._sound: bool = False
        self._heating: bool = False
        self._filter_remain: float = 0.0
        self._error_code: int = 0
        self.__failed_connects: int = 0

    @property
    def mac(self):
        return self._mac

    def get(self, keep_connection: bool = False) -> dict:
        """
        Get current device state
        :param keep_connection: should we keep connection to device or disconnect after getting data
        :return:
          dictionary with device state
        """
        try:
            self._connect()
            response = self._get_data_from_breezer()
        finally:
            if not keep_connection:
                self._disconnect()

        self._decode_response(response)
        self.__detect_heating_state()
        common = self.__generate_common_json()
        model_specific_data = self._generate_model_specific_json()

        return {**common, **model_specific_data}

    def _generate_model_specific_json(self) -> dict:
        return {
            "code": 200,
            "timer": self._timer,
            "time": self._time,
            "productivity": self._productivity,
            "fw_version": self._fw_version,
        }

    def __generate_common_json(self) -> dict:
        """
        Generates dict with common parameters based on class properties
        :return: dict of common properties
        """
        return {
            "state": self.state,
            "heater": self.heater,
            "heating": self.heating,
            "sound": self.sound,
            "mode": self.mode,
            "out_temp": self.out_temp,
            "in_temp": self.in_temp,
            "heater_temp": self.target_temp,
            "fan_speed": self.fan_speed,
            "filter_remain": self.filter_remain,
            "time": strftime("%H:%M", localtime()),
            "request_error_code": self._error_code,
            "model": self.model,
        }

    @property
    def fan_speed(self):
        return self._fan_speed

    @fan_speed.setter
    def fan_speed(self, new_speed: int):
        if 0 <= new_speed <= 6:
            self._fan_speed = new_speed

        else:
            _LOGGER.warning("Incorrect new fan speed. Will use 1 instead")
            self._fan_speed = 1

        # self.set({"fan_speed": new_speed})

    def __detect_heating_state(self,
                               in_temp: int = None,
                               out_temp: int = None,
                               target_temp: int = None,
                               heater: str = None) -> None:
        """
        Tries to guess is heater working right now
        :param in_temp: air intake temperature
        :param out_temp: ait outtake temperature
        :param target_temp: target temperature for heater
        :param heater: heater state
        :return: None
        """
        if in_temp is None:
            in_temp = self.in_temp
        if out_temp is None:
            out_temp = self.out_temp
        if target_temp is None:
            target_temp = self.target_temp
        if heater is None:
            heater = self.heater

        if heater == "off":
            self.heating = "off"
        else:
            if in_temp < target_temp and out_temp - target_temp < 3:
                self.heating = "on"
            else:
                self.heating = "off"

    def _get_data_from_breezer(self):
        have_data_from_breezer: bool = False
        self._try_write, request = self.get_status_command

        i = 0
        try:
            while i < 10:
                if self._delegation.haveNewData:
                    have_data_from_breezer = True
                    break
                else:
                    self._btle.waitForNotifications(1.0)
                i += 1
            else:
                _LOGGER.debug("Waiting too long for data")
                self.notify.read()
        except btle.BTLEDisconnectError as e:
            _LOGGER.debug("Got %s while waiting for notification", str(e))

        if have_data_from_breezer:
            self._data = self._delegation.data
            result = self._data

        else:
            raise TionException("s3 _get_data_from_breezer", "Could not get breezer state")

        return result

    @property
    def get_status_command(self) -> bytearray:
        return self.create_command(self.command_REQUEST_PARAMS)

    def create_command(self, command: int) -> bytearray:
        command_special = 1 if command == self.command_PAIR else 0
        return bytearray([self.command_prefix, command, command_special, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          self.command_suffix])

    def _connect(self, need_notifications: bool = True):
        _LOGGER.debug("Connecting")
        try:
            self._btle.connect(self.mac, btle.ADDR_TYPE_RANDOM)
            for tc in self._btle.getCharacteristics():
                if tc.uuid == self.uuid_notify:
                    self.notify = tc
                if tc.uuid == self.uuid_write:
                    self.write = tc
            if need_notifications:
                self._enable_notifications()
            else:
                _LOGGER.debug("Notifications was not requested")
            self.__failed_connects = 0
        except btle.BTLEDisconnectError as e:
            _LOGGER.warning("Got BTLEDisconnectError:%s", str(e))
            if self.__failed_connects < 1:
                self.__failed_connects += 1
                _LOGGER.debug("Will try again.")
                time.sleep(2)
                self._connect(need_notifications)
            else:
                raise e

    def _disconnect(self):
        self._btle.disconnect()

    def _enable_notifications(self):
        _LOGGER.debug("Enabling notification")
        setup_data = b"\x01\x00"

        _LOGGER.debug("Notify handler is %s", self.notify.getHandle())
        notify_handle = self.notify.getHandle() + 1

        _LOGGER.debug("Will write %s to %s handle", setup_data, notify_handle)
        result = self._btle.writeCharacteristic(notify_handle, setup_data, withResponse=True)
        _LOGGER.debug("Result is %s", result)
        self._btle.withDelegate(self._delegation)
        _LOGGER.debug("Delegation enabled")
        self._delegation.setReadTopic(self.notify)
        _LOGGER.debug("enable_notification is done")

    def _decode_response(self, response):
        _LOGGER.debug("Data is %s", bytes(response).hex())
        try:
            self._fan_speed = int(list("{:02x}".format(response[2]))[1])
            self._mode = int(list("{:02x}".format(response[2]))[0])
            self._heater = response[4] & 1
            self._state = response[4] >> 1 & 1
            self._target_temp = response[3]
            self._sound = response[4] >> 3 & 1
            self._out_temp = self.decode_temperature(response[7])
            self._in_temp = self.decode_temperature(response[8])
            self._filter_remain = response[10] * 256 + response[9]
            self._error_code = response[13]

            self._timer = self._process_status(response[4] >> 2 & 1)
            self._time = "{}:{}".format(response[11], response[12])
            self._productivity = response[14]
            self._fw_version = "{:02x}{:02x}".format(response[18], response[17])
        except IndexError as e:
            raise TionException("s3 _decode_response", "Got bad response from Tion '%s': %s while parsing" % (response,
                                                                                                              str(e)))

    @staticmethod
    def decode_temperature(raw: int) -> int:
        """ Converts temperature from bytes with addition code to int
        Args:
          raw: raw temperature value from Tion
        Returns:
          Integer value for temperature
        """
        barrier = 0b10000000
        return raw if raw < barrier else -(~(raw - barrier) + barrier + 1)

    def _process_status(self, code: int) -> str:
        try:
            status = self.statuses[code]
        except IndexError:
            status = 'unknown'
        return status

    @staticmethod
    def _decode_state(state: bool) -> str:
        return "on" if state else "off"

    @staticmethod
    def _encode_state(state: str) -> bool:
        return state == "on"

    @property
    def state(self) -> str:
        return self._decode_state(self._state)

    @state.setter
    def state(self, new_state: str):
        self._state = self._encode_state(new_state)

    @property
    def heater(self) -> str:
        return self._decode_state(self._heater)

    @heater.setter
    def heater(self, new_state: str):
        self._heater = self._encode_state(new_state)

    @property
    def target_temp(self) -> int:
        return self._target_temp

    @target_temp.setter
    def target_temp(self, new_temp: int):
        self._target_temp = new_temp

    @property
    def in_temp(self):
        """Income air temperature"""
        return self._in_temp

    @property
    def out_temp(self):
        """Outcome air temperature"""
        return self._out_temp

    @property
    def sound(self) -> str:
        return self._decode_state(self._sound)

    @sound.setter
    def sound(self, new_state: str):
        self._sound = self._encode_state(new_state)

    @property
    def filter_remain(self) -> float:
        return self._filter_remain

    @property
    def heating(self) -> str:
        return self._decode_state(self._heating)

    @heating.setter
    def heating(self, new_state: str):
        self._heating = self._encode_state(new_state)

    @property
    def mode(self):
        return self._process_mode(self._mode)

    @property
    def model(self) -> str:
        return self._model

    def _process_mode(self, mode_code: int) -> str:
        try:
            mode = self.modes[mode_code]
        except IndexError:
            mode = 'outside'
        return mode


MAC = 'FF:22:F3:1E:F3:A6'
test = TionTest(MAC)
_LOGGER.debug(test.get())
