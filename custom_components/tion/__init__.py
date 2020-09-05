"""The Tion breezer component."""
import logging
import datetime
from typing import Dict, Coroutine

from bluepy import btle
from tion_btle.s3 import s3 as tion
from .const import DOMAIN, TION_SCHEMA, CONF_KEEP_ALIVE, CONF_AWAY_TEMP, CONF_MAC
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass, config_entry: ConfigEntry):
    _LOGGER.info("Setting up %s ", config_entry.entry_id)

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    master = get_master(hass)
    hass.data[DOMAIN]['master'] = master

    instance = TionInstance(hass, config_entry)
    hass.data[DOMAIN][config_entry.entry_id] = instance
    master.add_instance(instance)
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
        self.__fw_version: str = None
        self.__in_temp: int = None
        self.__filter_remain: int = None

        # delay before next update if we got btle.BTLEDisconnectError
        self._delay: int = 600
        self._next_update: int = 0

        self.__tion = tion(self.config[CONF_MAC])

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

    def update(self):
        """get data from Tion"""
        _LOGGER.info("Starting update for tion instance %s" % self._entry_id)

        def decode_state(state: str) -> bool:
            return True if state == "on" else False

        response = {}

        try:
            response = self.__tion.get()

            self.__out_temp = response["out_temp"]
            self.__heater_temp = response["heater_temp"]
            self.__is_on = decode_state(response["status"])
            self.__is_heater_on = decode_state(response["heater"])
            self.__fan_speed = response["fan_speed"]
            self.__is_heating = decode_state(response["is_heating"])
            self.__fw_version = response["fw_version"]
            self.__in_temp = response["in_temp"]
            self.__filter_remain = response["filter_remain"]
            self._next_update = 0
        except btle.BTLEDisconnectError as e:
            _LOGGER.critical("Got exception %s", str(e))
            raise e
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
            kwargs["status"] = "on" if kwargs["is_on"] else "off"
            del kwargs["is_on"]
        if "heater" in kwargs:
            kwargs["heater"] = "on" if kwargs["heater"] else "off"
        if "fan_speed" in kwargs:
            kwargs["fan_speed"] = int(kwargs["fan_speed"])

        args = ', '.join('%s=%r' % x for x in kwargs.items())
        _LOGGER.info("Need to set: " + args)
        self.__tion.set(kwargs)

    @property
    def entry_id(self):
        return self._entry_id


class TionMaster:
    def __init__(self, hass: HomeAssistant):
        self.hass: HomeAssistant = hass
        self._instances: Dict[str, TionInstance] = {}
        self._entities: Dict[str, Coroutine] = {}
        async_track_time_interval(self.hass, self.async_update_state, datetime.timedelta(seconds=60))

    async def async_update_state(self, time=None):
        """
        Home Assistant will call this function from time to time

        :param time: timestamp of call
        :return: None
        """
        for instance in self._instances.keys():
            self.update(instance)
            await self.update_state(instance)

    def update(self, entity_id: str):
        """Get data from Tion devices"""
        _LOGGER.debug("Updating %s" % entity_id)
        self._instances[entity_id].update()

    async def update_state(self, entity_id: str):
        """Call write_state for entities to update data in Home Assistant"""
        await self._entities[entity_id]

    def add_instance(self, instance: TionInstance):
        """Add instance to list"""
        self._instances[instance.entry_id] = instance

    def add_entity(self, entity_id: str, callback: Coroutine):
        """Add entity (sensor, climate, etc) to list for subscribing to updates"""
        self._entities[entity_id] = callback


def get_master(hass: HomeAssistant) -> TionMaster:
    try:
        master = hass.data[DOMAIN]['master']
    except KeyError:
        # no master defined
        master = TionMaster(hass)
    return master
