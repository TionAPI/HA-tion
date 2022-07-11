"""The Tion breezer component."""
from __future__ import annotations

import datetime
import logging
import math
from datetime import timedelta
from functools import cached_property

import tion_btle
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from tion_btle.tion import Tion, MaxTriesExceededError
from .const import DOMAIN, TION_SCHEMA, CONF_KEEP_ALIVE, CONF_AWAY_TEMP, CONF_MAC, PLATFORMS
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass, config_entry: ConfigEntry):
    _LOGGER.info("Setting up %s ", config_entry.unique_id)

    hass.data.setdefault(DOMAIN, {})

    hass.data[DOMAIN][config_entry.unique_id] = TionInstance(hass, config_entry)
    await hass.data[DOMAIN][config_entry.unique_id].async_config_entry_first_refresh()
    hass.config_entries.async_setup_platforms(config_entry, PLATFORMS)
    return True


class TionInstance(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):

        self._config_entry: ConfigEntry = config_entry

        self.__keep_alive: int = 60
        try:
            self.__keep_alive = self.config[CONF_KEEP_ALIVE]
        except KeyError:
            pass

        # delay before next update if we got btle.BTLEDisconnectError
        self._delay: int = 600

        self.__tion: Tion = self.getTion(self.model, self.config[CONF_MAC])
        self.__keep_alive = datetime.timedelta(seconds=self.__keep_alive)
        self._delay = datetime.timedelta(seconds=self._delay)

        if self._config_entry.unique_id is None:
            _LOGGER.critical(f"Unique id is None for {self.config_entry.title}! "
                             f"Will fix it by using {self.unique_id}")
            hass.config_entries.async_update_entry(
                entry=self._config_entry,
                unique_id=self.unique_id,
            )
            _LOGGER.critical("Done! Please restart Home Assistant.")

        super().__init__(
            name=self.config['name'] if 'name' in self.config else TION_SCHEMA['name']['default'],
            hass=hass,
            logger=_LOGGER,
            update_interval=self.__keep_alive,
            update_method=self.async_update_state,
        )

    @property
    def config(self) -> dict:
        try:
            data = dict(self._config_entry.data or {})
        except AttributeError:
            data = {}

        try:
            options = self._config_entry.options or {}
            data.update(options)
        except AttributeError:
            pass
        return data

    @staticmethod
    def _decode_state(state: str) -> bool:
        return True if state == "on" else False

    async def async_update_state(self):
        self.logger.info("Tion instance update started")
        response: dict[str, str | bool | int] = {}

        try:
            response = await self.__tion.get()
            self.update_interval = self.__keep_alive

        except MaxTriesExceededError as e:
            _LOGGER.critical("Got exception %s", str(e))
            _LOGGER.critical("Will delay next check")
            self.update_interval = self._delay
            raise UpdateFailed("MaxTriesExceededError")
        except Exception as e:
            _LOGGER.critical('Response is %s' % response)
            raise e

        response["is_on"]: bool = self._decode_state(response["state"])
        response["heater"]: bool = self._decode_state(response["heater"])
        response["is_heating"] = self._decode_state(response["heating"])
        response["filter_remain"] = math.ceil(response["filter_remain"])
        response["fan_speed"] = int(response["fan_speed"])

        self.logger.debug(f"Result is {response}")
        return response

    @property
    def away_temp(self) -> int:
        """Temperature for away mode"""
        return self.config[CONF_AWAY_TEMP] if CONF_AWAY_TEMP in self.config else TION_SCHEMA[CONF_AWAY_TEMP]['default']

    async def set(self, **kwargs):
        if "fan_speed" in kwargs:
            kwargs["fan_speed"] = int(kwargs["fan_speed"])

        original_args = kwargs.copy()
        if "is_on" in kwargs:
            kwargs["state"] = "on" if kwargs["is_on"] else "off"
            del kwargs["is_on"]
        if "heater" in kwargs:
            kwargs["heater"] = "on" if kwargs["heater"] else "off"

        args = ', '.join('%s=%r' % x for x in kwargs.items())
        _LOGGER.info("Need to set: " + args)
        await self.__tion.set(kwargs)
        self.data.update(original_args)
        self.async_update_listeners()

    @staticmethod
    def getTion(model: str, mac: str) -> tion_btle.TionS3 | tion_btle.TionLite | tion_btle.TionS4:
        if model == 'S3':
            from tion_btle.s3 import TionS3 as Breezer
        elif model == 'S4':
            from tion_btle.s4 import TionS4 as Breezer
        elif model == 'Lite':
            from tion_btle.lite import TionLite as Breezer
        else:
            raise NotImplementedError("Model '%s' is not supported!" % model)
        return Breezer(mac)

    async def connect(self):
        return await self.__tion.connect()

    async def disconnect(self):
        return await self.__tion.disconnect()

    @property
    def device_info(self):
        info = {"identifiers": {(DOMAIN, self.unique_id)}, "name": self.name, "manufacturer": "Tion",
                "model": self.data.get("model"), "type": None}
        if self.data.get("fw_version") is not None:
            info['sw_version'] = self.data.get("fw_version")
        return info

    @cached_property
    def unique_id(self):
        return self.config[CONF_MAC]

    @cached_property
    def supported_air_sources(self) -> list[str]:
        if self.model == "S3":
            return ["outside", "mixed", "recirculation"]
        else:
            return ["outside", "recirculation"]

    @cached_property
    def model(self) -> str:
        try:
            model = self.config['model']
        except KeyError:
            _LOGGER.warning(f"Model was not found in config. "
                            f"Please update integration settings! Config is {self.config}")
            _LOGGER.warning("Assume that model is S3")
            model = 'S3'
        return model
