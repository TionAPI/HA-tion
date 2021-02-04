"""The Tion breezer component."""
import logging
import datetime
from typing import Union

from bluepy import btle
from tion_btle.tion import tion
from tion_btle.s3 import S3
from .const import DOMAIN, TION_SCHEMA, CONF_KEEP_ALIVE, CONF_AWAY_TEMP, CONF_MAC
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass, config_entry: ConfigEntry):
    _LOGGER.info("Setting up %s ", config_entry.unique_id)

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][config_entry.entry_id] = TionInstance(hass, config_entry)
    return True


class TionInstance:
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        self.hass: HomeAssistant = hass
        self._config_entry: ConfigEntry = config_entry

        self._entry_id: str = self._config_entry.entry_id

        self.__keep_alive: int = 60
        try:
            self.__keep_alive = self.config[CONF_KEEP_ALIVE]
        except KeyError:
            pass

        self.__out_temp: int = None
        self.__fan_speed: int = None
        self.__heater_temp: int = None

        self.__is_on: bool = None
        self.__is_heater_on: bool = None
        self.__is_heating: bool = None
        self.__fw_version: Union[str, None] = None
        self.__in_temp: int = None
        self.__filter_remain: int = None

        # delay before next update if we got btle.BTLEDisconnectError
        self._delay: int = 600
        self._next_update: int = 0

        try:
            model = self.config['model']
        except KeyError:
            _LOGGER.warning("Model was not found in config. Please update integration settings!")
            _LOGGER.warning("Assume that model is S3")
            model = 'S3'

        self.__tion: tion = self.getTion(model, self.config[CONF_MAC])

        hass.loop.create_task(self.start_up())

    @property
    def config(self) -> dict:
        config = {}
        if hasattr(self._config_entry, 'options'):
            if any(self._config_entry.options):
                config = self._config_entry.options
        if not any(config):
            if hasattr(self._config_entry, 'data'):
                if any(self._config_entry.data):
                    config = self._config_entry.data
        return config

    async def start_up(self):
        await self.hass.config_entries.async_forward_entry_setup(self._config_entry, 'climate')
        await self.hass.config_entries.async_forward_entry_setup(self._config_entry, 'sensor')

    async def async_update_state(self, time=None, force: bool = False, keep_connection: bool = False):
        _LOGGER.debug("Tion instance updated at %s" % time)

        def decode_state(state: str) -> bool:
            return True if state == "on" else False

        _LOGGER.debug("Update fired force = " + str(force) + ". Keep connection is " + str(keep_connection))
        if time:
            _LOGGER.debug("Now is %s", time)
            now = int(time.timestamp())
        else:
            now = 0
        response = {}
        if self._next_update <= now or force:
            try:
                response = self.__tion.get(keep_connection)

                self.__out_temp = response["out_temp"]
                self.__heater_temp = response["heater_temp"]
                self.__is_on = decode_state(response["state"])
                self.__is_heater_on = decode_state(response["heater"])
                self.__fan_speed = response["fan_speed"]
                self.__is_heating = decode_state(response["heating"])
                self.__in_temp = response["in_temp"]
                self.__filter_remain = response["filter_remain"]
                self._next_update = 0
                if type(self.__tion) is S3:
                    # Only S3 report firmware version
                    self.__fw_version = response["fw_version"]
                else:
                    self.__fw_version = None

            except btle.BTLEDisconnectError as e:
                _LOGGER.critical("Got exception %s", str(e))
                _LOGGER.critical("Will delay next check")
                self._next_update = now + self._delay
            except Exception as e:
                _LOGGER.critical('Response is %s' % response)
                raise e
        return True

    @property
    def mac(self):
        """Device MAC adders"""
        return self.config[CONF_MAC]

    @property
    def away_temp(self) -> int:
        """Temperature for away mode"""
        return self.config[CONF_AWAY_TEMP] if CONF_AWAY_TEMP in self.config else TION_SCHEMA[CONF_AWAY_TEMP]['default']

    @property
    def keep_alive(self) -> int:
        """Update interval"""
        return self.config[CONF_KEEP_ALIVE] if CONF_KEEP_ALIVE in self.config else TION_SCHEMA[CONF_KEEP_ALIVE][
            'default']

    @property
    def name(self) -> str:
        """Instance name"""
        return self.config['name'] if 'name' in self.config else TION_SCHEMA['name']['default']

    @property
    def keep_alive(self) -> int:
        return self.__keep_alive

    @keep_alive.setter
    def keep_alive(self, value: int):
        self.__keep_alive = value

    @property
    def fan_speed(self) -> int:
        return self.__fan_speed

    @property
    def heater_temp(self) -> int:
        return self.__heater_temp

    @property
    def out_temp(self) -> int:
        return self.__out_temp

    @property
    def is_on(self) -> bool:
        return self.__is_on

    @property
    def is_heater_on(self) -> bool:
        return self.__is_heater_on

    @property
    def is_heating(self) -> bool:
        return self.__is_heating

    @property
    def fw_version(self) -> str:
        return self.__fw_version

    @property
    def in_temp(self) -> int:
        return self.__in_temp

    @property
    def filter_remain(self) -> int:
        return self.__filter_remain

    async def set(self, **kwargs):
        if "is_on" in kwargs:
            kwargs["state"] = "on" if kwargs["is_on"] else "off"
            del kwargs["is_on"]
        if "heater" in kwargs:
            kwargs["heater"] = "on" if kwargs["heater"] else "off"
        if "fan_speed" in kwargs:
            kwargs["fan_speed"] = int(kwargs["fan_speed"])

        args = ', '.join('%s=%r' % x for x in kwargs.items())
        _LOGGER.info("Need to set: " + args)
        self.__tion.set(kwargs)

    @staticmethod
    def getTion(model: str, mac: str) -> tion:
        if model == 'S3':
            from tion_btle.s3 import S3 as Tion
        elif model == 'Lite':
            from tion_btle.lite import Lite as Tion
        else:
            raise NotImplementedError("Model '%s' is not supported!" % model)
        return Tion(mac)

    @property
    def model(self) -> str:
        return self.__tion.model

    @property
    def air_mode(self) -> str:
        return self.__tion.mode

    def connect(self):
        return self.__tion.connect()

    def disconnect(self):
        return self.__tion.disconnect()

    @property
    def device_info(self):
        info = {"identifiers": {(DOMAIN, self.mac)}, "name": self.name, "manufacturer": "Tion",
                "model": self.model, "type": None}
        if self.fw_version is not None:
            info['sw_version'] = self.fw_version
        return info
