"""Adds support for generic thermostat units."""
import asyncio
import logging
import time
import datetime
from abc import abstractmethod
from bluepy import btle
from typing import Tuple, Callable

from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import TEMP_CELSIUS
import voluptuous as vol

from homeassistant.components.climate import ClimateEntity
from homeassistant.core import callback
from homeassistant.helpers import condition, device_registry as dr
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import (async_track_state_change, async_track_time_interval, )
from homeassistant.helpers.restore_state import RestoreEntity
from .const import *

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_MAC): cv.string,
        vol.Optional(CONF_TARGET_TEMP): vol.Coerce(float),
        vol.Optional(CONF_KEEP_ALIVE, default=30): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(CONF_INITIAL_HVAC_MODE): vol.In(
            [HVAC_MODE_FAN_ONLY, HVAC_MODE_HEAT, HVAC_MODE_OFF]
        ),
        vol.Optional(CONF_AWAY_TEMP): vol.Coerce(float),
    }
)

devices = []


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_devices):
    """Setup entry"""
    config = {}
    if hasattr(config_entry, 'options'):
        if any(config_entry.options):
            config = config_entry.options
    if not any(config):
        if hasattr(config_entry, 'data'):
            if any(config_entry.data):
                config = config_entry.data

    mac = config[CONF_MAC]
    if mac not in devices:
        devices.append(mac)
        async_add_devices([TionClimateEntity(config, config_entry.entry_id, hass)])
    else:
        _LOGGER.warning("Device with mac %s was already configured via configuration.yaml" % mac)
        _LOGGER.warning(
            "Please use UI configuration. Support for configuration via configuration.yaml will be dropped in v2.0.0")
    return True


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the generic thermostat platform."""
    mac = config.get(CONF_MAC)
    if mac not in devices:
        devices.append(mac)
        async_add_entities(
            [
                TionClimateYaml(
                    config.get(CONF_NAME),
                    config.get(CONF_MAC),
                    config.get(CONF_TARGET_TEMP),
                    config.get(CONF_KEEP_ALIVE),
                    config.get(CONF_INITIAL_HVAC_MODE),
                    config.get(CONF_AWAY_TEMP),
                    hass.config.units.temperature_unit,
                )
            ]
        )
    else:
        _LOGGER.warning("Device with mac %s was already configured via user interface" % mac)
        _LOGGER.warning(
            "Please use UI configuration. Support for configuration via configuration.yaml will be dropped in v2.0.0")


class TionClimateDevice(ClimateEntity, RestoreEntity):
    """Representation of a Tion device."""
    def __init__(
            self,
            name=None,
            mac=None,
            target_temp=22,
            keep_alive=None,
            initial_hvac_mode=None,
            away_temp=None,
            unit=TEMP_CELSIUS
    ):

        self._name = name
        self._keep_alive = keep_alive
        self._last_mode = None
        self._saved_target_temp = None
        self._is_on = False
        self._heater: bool = False
        self._cur_temp = None
        self._target_temp = target_temp
        self._unit = unit
        self._support_flags = SUPPORT_FLAGS
        self._preset = PRESET_NONE
        if away_temp:
            self._support_flags = SUPPORT_FLAGS | SUPPORT_PRESET_MODE
        self._away_temp = away_temp
        self._is_boost: bool = False
        self._saved_fan_mode = None

        self._hvac_list = [HVAC_MODE_HEAT, HVAC_MODE_FAN_ONLY, HVAC_MODE_OFF]
        self._fan_speed = 1
        self._is_heating: bool = False
        self.target_temp = target_temp
        # tion part
        self._tion_entry = None
        self._mac = mac
        self._delay = 600  # if we could not connect wait a little
        self._next_update = 0
        self._fw_version = None

    async def restore_states(self):
        # Check If we have an old state
        old_state = await self.async_get_last_state()
        if old_state is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    self._target_temp = self.target_temp
                    _LOGGER.warning(
                        "Undefined target temperature, falling back to %s",
                        self._target_temp,
                    )
                else:
                    self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
            if old_state.attributes.get(ATTR_PRESET_MODE):
                self._preset = old_state.attributes.get(ATTR_PRESET_MODE)

        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                self._target_temp = self.target_temp

            _LOGGER.warning("No previously saved temperature, setting to %s", self._target_temp)

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def min_temp(self) -> float:
        """Minimum temperature that allowed by Tion breezer."""
        return 0

    @property
    def max_temp(self) -> float:
        """Maximum temperature that allowed by Tion breezer."""
        return 30

    @property
    def hvac_mode(self):
        """Return current operation."""
        if self._is_on:
            if self._heater:
                return HVAC_MODE_HEAT
            else:
                return HVAC_MODE_FAN_ONLY
        else:
            return HVAC_MODE_OFF

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.
        Need to be one of CURRENT_HVAC_*.
        """
        if self._is_on:
            if self._is_heating:
                current_hvac_operation = CURRENT_HVAC_HEAT
            else:
                current_hvac_operation = CURRENT_HVAC_FAN
        else:
            current_hvac_operation = CURRENT_HVAC_OFF
        return current_hvac_operation

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp."""
        return self._preset

    @property
    def preset_modes(self):
        """Return a list of available preset modes or PRESET_NONE if _away_temp is undefined."""
        modes = [PRESET_NONE, PRESET_BOOST, PRESET_SLEEP]
        if self._away_temp:
            modes.append(PRESET_AWAY)
        return modes

    @property
    def mac(self):
        return self._mac

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        _LOGGER.info("Need to set mode to %s, current mode is %s", hvac_mode, self.hvac_mode)
        if hvac_mode == self.hvac_mode:
            # user pressed current mode at UI card. What should we do?
            if hvac_mode == HVAC_MODE_HEAT:
                hvac_mode = HVAC_MODE_FAN_ONLY
            elif hvac_mode == HVAC_MODE_OFF:
                try:
                    if self._last_mode:
                        hvac_mode = self._last_mode
                        self._last_mode = None
                except AttributeError:
                    hvac_mode = HVAC_MODE_FAN_ONLY

        if hvac_mode == HVAC_MODE_HEAT:
            await self._async_set_state(heater=True, is_on=True)
        elif hvac_mode == HVAC_MODE_FAN_ONLY:
            await self._async_set_state(heater=False, is_on=True)
        elif hvac_mode == HVAC_MODE_OFF:
            if self._last_mode is None:
                self._last_mode = self.hvac_mode
            await self._async_set_state(is_on=False)
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new preset mode."""
        actions = []
        _LOGGER.debug("Going to change preset mode from %s to %s", self.preset_mode, preset_mode)
        if preset_mode == PRESET_AWAY and self.preset_mode != PRESET_AWAY:
            _LOGGER.info("Going to AWAY mode. Will save target temperature %s", self.target_temperature)
            self._saved_target_temp = self.target_temperature
            actions.append([self._async_set_state, {'heater_temp': self._away_temp}])

        if preset_mode != PRESET_AWAY and self.preset_mode == PRESET_AWAY and self._saved_target_temp:
            # retuning from away mode
            _LOGGER.info("Returning from AWAY mode: will set saved temperature %s", self._saved_target_temp)
            actions.append([self._async_set_state, {'heater_temp': self._saved_target_temp}])
            self._saved_target_temp = None

        if preset_mode == PRESET_SLEEP and self.preset_mode != PRESET_SLEEP:
            _LOGGER.info("Going to night mode: will save fan_speed: %s", self.fan_mode)
            if self._saved_fan_mode is None:
                self._saved_fan_mode = int(self.fan_mode)
            actions.append([self.async_set_fan_mode, {'fan_mode': min(int(self.fan_mode), self.sleep_max_fan_mode)}])

        if preset_mode == PRESET_BOOST and not self._is_boost:
            self._is_boost = True
            if self._saved_fan_mode is None:
                self._saved_fan_mode = int(self.fan_mode)
            actions.append([self.async_set_fan_mode, {'fan_mode': self.boost_fan_mode}])

        if self.preset_mode in [PRESET_BOOST, PRESET_SLEEP] and preset_mode not in [PRESET_BOOST, PRESET_SLEEP]:
            # returning from boost or sleep mode
            _LOGGER.info("Returning from %s mode. Going to set fan speed %d", self.preset_mode, self._saved_fan_mode)
            if self.preset_mode == PRESET_BOOST:
                self._is_boost = False

            if self._saved_fan_mode is not None:
                actions.append([self.async_set_fan_mode, {'fan_mode': self._saved_fan_mode}])
                self._saved_fan_mode = None

        self._preset = preset_mode
        try:
            self._tion_entry.connect()
            for a in actions:
                await a[0](**a[1])
            self._preset = preset_mode
            await self._async_update_state()
        finally:
            self._tion_entry.disconnect()

    @property
    def boost_fan_mode(self) -> int:
        """Fan speed for boost mode

        :return: maximum of supported fan_modes
        """
        return max(self.fan_modes)

    @property
    def sleep_max_fan_mode(self) -> int:
        """Maximum fan speed for sleep mode"""
        return 2

    @property
    def fan_modes(self):
        return [1, 2, 3, 4, 5, 6]

    @property
    def precision(self):
        """Return the precision of the system."""
        return PRECISION_WHOLE

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 1

    @property
    def unique_id(self):
        return self.mac

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        if self._keep_alive:
            async_track_time_interval(self.hass, self._async_update_state, self._keep_alive)
        await self._async_update_state(force=True)
        await self.restore_states()

    async def async_set_fan_mode(self, fan_mode):
        if self.preset_mode == PRESET_SLEEP:
            if int(fan_mode) > self.sleep_max_fan_mode:
                _LOGGER.info("Fan speed %s was required, but I'm in SLEEP mode, so it should not be greater than %d",
                             self.sleep_max_fan_mode)
                fan_mode = self.sleep_max_fan_mode

        if (self.preset_mode == PRESET_BOOST and self._is_boost) and fan_mode != self.boost_fan_mode:
            _LOGGER.debug("I'm in boost mode. Will ignore requested fan speed %s" % fan_mode)
            fan_mode = self.boost_fan_mode
        if fan_mode != self.fan_mode or not self._is_on:
            self._fan_speed = fan_mode
            await self._async_set_state(fan_speed=fan_mode, is_on=True)
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._target_temp = temperature
        await self._async_set_state(heater_temp=temperature)
        self.async_write_ha_state()

    @abstractmethod
    async def _async_update_state(self, time=None, force: bool = False, keep_connection: bool = False) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def _async_set_state(self, **kwargs):
        raise NotImplementedError

    @property
    def icon(self):
        return 'mdi:air-purifier'


class TionClimateEntity(TionClimateDevice):
    def __init__(self, config: ConfigEntry, entry_id, hass: HomeAssistant):
        super(TionClimateEntity, self).__init__()

        self._entry_id = entry_id
        self.hass: HomeAssistant = hass
        self._tion_entry = self.hass.data[DOMAIN][self._entry_id]
        self._keep_alive: datetime.timedelta = datetime.timedelta(seconds=self._tion_entry.keep_alive)
        self._name = self._tion_entry.name
        self._away_temp = self._tion_entry.away_temp
        self._support_flags = SUPPORT_FLAGS | SUPPORT_PRESET_MODE

    @property
    def mac(self):
        return self._tion_entry.mac

    @property
    def fan_mode(self):
        return self._tion_entry.fan_speed

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._tion_entry.heater_temp

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._tion_entry.out_temp

    async def _async_set_state(self, **kwargs):
        await self._tion_entry.set(**kwargs)
        await self._async_update_state(force=True, keep_connection=False)

    async def _async_update_state(self, time=None, force: bool = False, keep_connection: bool = False) -> dict:
        """called every self._keep_alive"""
        await self._tion_entry.async_update_state(time, force, keep_connection)
        self._is_on = self._tion_entry.is_on
        self._heater = self._tion_entry.is_heater_on
        self._is_heating = self._tion_entry.is_heating
        try:
            self._fw_version = self._tion_entry.fw_version
        except Exception:
            self._fw_version = None

        device_registry = await dr.async_get_registry(self.hass)
        info = self.device_info
        del (info['type'])
        device_registry.async_get_or_create(config_entry_id=self._entry_id, **info)

        if self.fan_mode != self.boost_fan_mode and (self._is_boost or self.preset_mode == PRESET_BOOST):
            _LOGGER.warning(
                "I'm in boost mode, but current speed %d is not equal boost speed %d. Dropping boost mode" % (
                    self.fan_mode, self.boost_fan_mode))
            self._is_boost = False
            self._preset = PRESET_NONE

        self.async_write_ha_state()

    @property
    def device_info(self):
        return self._tion_entry.device_info

    @property
    def device_state_attributes(self):
        attributes = {
            'air_mode': self._tion_entry.air_mode,
            'in_temp': self._tion_entry.in_temp
        }
        return attributes


class TionClimateYaml(TionClimateDevice):
    def __init__(self, name, mac, target_temp, keep_alive, initial_hvac_mode, away_temp, unit):
        super(TionClimateYaml, self).__init__(name, mac, target_temp, keep_alive, initial_hvac_mode, away_temp, unit)
        from tion_btle.s3 import S3 as tion
        self._tion = tion(self.mac)

    async def _async_set_state(self, **kwargs):
        if "is_on" in kwargs:
            kwargs["state"] = "on" if kwargs["is_on"] else "off"
            del kwargs["is_on"]
        if "heater" in kwargs:
            kwargs["heater"] = "on" if kwargs["heater"] else "off"
        if "fan_speed" in kwargs:
            kwargs["fan_speed"] = int(kwargs["fan_speed"])

        args = ', '.join('%s=%r' % x for x in kwargs.items())
        _LOGGER.info("Need to set: " + args)
        self._tion.set(kwargs)
        await self._async_update_state(force=True, keep_connection=False)

    async def _async_update_state(self, time=None, force: bool = False, keep_connection: bool = False) -> dict:
        def decode_state(state: str) -> bool:
            return True if state == "on" else False

        _LOGGER.debug("Update fired force = " + str(force) + ". Keep connection is " + str(keep_connection))
        if time:
            _LOGGER.debug("Now is %s", time)
            now = int(time.timestamp())
        else:
            now = 0

        if self._next_update <= now or force:
            try:
                response = self._tion.get(keep_connection)

                self._cur_temp = response["out_temp"]
                self._target_temp = response["heater_temp"]
                self._is_on = decode_state(response["state"])
                self._heater = decode_state(response["heater"])
                self._fan_speed = response["fan_speed"]
                self._is_heating = decode_state(response["heating"])
                self._fw_version = response["fw_version"]
                self.async_write_ha_state()
                self._next_update = 0
                if self.fan_mode != self.boost_fan_mode and (self._is_boost or self.preset_mode == PRESET_BOOST):
                    _LOGGER.warning(
                        "I'm in boost mode, but current speed %d is not equal boost speed %d. Dropping boost mode" % (
                            self.fan_mode, self.boost_fan_mode))
                    self._is_boost = False
                    self._preset = PRESET_NONE
            except btle.BTLEDisconnectError as e:
                _LOGGER.critical("Got exception %s", str(e))
                _LOGGER.critical("Will delay next check")
                self._next_update = now + self._delay
                response = {}
            except Exception as e:
                _LOGGER.critical('Response is %s' % response)
                raise e
        else:
            response = {}

        return response
