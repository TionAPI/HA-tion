"""The Tion breezer component."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import math

from bluepy import btle
from tion_btle.tion import tion
from .const import DOMAIN, TION_SCHEMA, CONF_KEEP_ALIVE, CONF_AWAY_TEMP, CONF_MAC, PLATFORMS
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_BTLE_COMMAND_EXECUTOR = ThreadPoolExecutor(max_workers=1)


async def btle_exec_helper(method, *args, **kwargs):
    return await asyncio.wrap_future(_BTLE_COMMAND_EXECUTOR.submit(method, *args, **kwargs))


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass, config_entry: ConfigEntry):
    _LOGGER.info("Setting up %s ", config_entry.unique_id)

    hass.data.setdefault(DOMAIN, {})

    hass.data[DOMAIN][config_entry.unique_id] = TionInstance(hass, config_entry)
    hass.config_entries.async_setup_platforms(config_entry, PLATFORMS)
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
        self.data = {}

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

    @staticmethod
    def _decode_state(state: str) -> bool:
        return True if state == "on" else False

    async def async_update_state(self, time=None, force: bool = False, keep_connection: bool = False):
        _LOGGER.debug("Tion instance updated at %s" % time)
        _LOGGER.debug("Update fired force = " + str(force) + ". Keep connection is " + str(keep_connection))
        if time:
            _LOGGER.debug("Now is %s", time)
            now = int(time.timestamp())
        else:
            now = 0
        response: dict[str, str | bool | int] = {}
        if self._next_update <= now or force:
            try:
                response = await btle_exec_helper(self.__tion.get, keep_connection)
                self._next_update = 0

            except btle.BTLEDisconnectError as e:
                _LOGGER.critical("Got exception %s", str(e))
                _LOGGER.critical("Will delay next check")
                self._next_update = now + self._delay
            except Exception as e:
                _LOGGER.critical('Response is %s' % response)
                raise e

        response["is_on"]: bool = self._decode_state(response["state"])
        response["heater"]: bool = self._decode_state(response["heater"])
        response["is_heating"] = self._decode_state(response["heating"])
        response["filter_remain"] = math.ceil(response["filter_remain"])
        response["fan_speed"] = int(response["fan_speed"])
        # Coordinator will do it for use in future
        self.data = response

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
    def name(self) -> str:
        """Instance name"""
        return self.config['name'] if 'name' in self.config else TION_SCHEMA['name']['default']

    @property
    def keep_alive(self) -> int:
        """Update interval"""
        return self.__keep_alive

    @keep_alive.setter
    def keep_alive(self, value: int):
        self.__keep_alive = value

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
        await btle_exec_helper(self.__tion.set, kwargs)
        self.data.update(kwargs)

    @staticmethod
    def getTion(model: str, mac: str) -> tion:
        if model == 'S3':
            from tion_btle.s3 import S3 as Tion
        elif model == 'S4':
            from tion_btle.s4 import S4 as Tion
        elif model == 'Lite':
            from tion_btle.lite import Lite as Tion
        else:
            raise NotImplementedError("Model '%s' is not supported!" % model)
        return Tion(mac)

    async def connect(self):
        return await btle_exec_helper(self.__tion.connect)

    async def disconnect(self):
        return await btle_exec_helper(self.__tion.disconnect)

    @property
    def device_info(self):
        info = {"identifiers": {(DOMAIN, self.mac)}, "name": self.name, "manufacturer": "Tion",
                "model": self.data.get("model"), "type": None}
        if self.data.get("fw_version") is not None:
            info['sw_version'] = self.data.get("fw_version")
        return info
