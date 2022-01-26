"""Adds support for generic thermostat units."""
import logging

import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import TEMP_CELSIUS
import voluptuous as vol

from homeassistant.components.climate import ClimateEntity

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import TionInstance
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


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Setup entry"""

    mac = hass.data[DOMAIN][config_entry.unique_id].mac

    if mac not in devices:
        devices.append(mac)
        async_add_entities([TionClimateEntity(config_entry.unique_id, hass)])
    else:
        _LOGGER.warning(f"Device {mac} is already configured! ")
    return True


class TionClimateEntity(ClimateEntity):
    """Representation of a Tion device."""

    def __init__(self, unique_id, hass: HomeAssistant):
        self.hass: HomeAssistant = hass
        self._tion_entry: TionInstance = self.hass.data[DOMAIN][unique_id]
        self._keep_alive: datetime.timedelta = datetime.timedelta(seconds=self._tion_entry.keep_alive)

        self._away_temp = self._tion_entry.away_temp
        self._support_flags = SUPPORT_FLAGS | SUPPORT_PRESET_MODE
        self._hvac_list = [HVAC_MODE_HEAT, HVAC_MODE_FAN_ONLY, HVAC_MODE_OFF]

        # saved states
        self._last_mode = None
        self._saved_target_temp = None
        self._saved_fan_mode = None

        # current state
        self._target_temp = None
        self._is_boost: bool = False
        self._fan_speed = 1

        self._preset = PRESET_NONE

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

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
        if self._tion_entry.data.get("is_on"):
            if self._tion_entry.data.get("heater"):
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
        if self._tion_entry.data.get("is_on"):
            if self._tion_entry.data.get("is_heating"):
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
        return self._tion_entry.mac

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        _LOGGER.info("Need to set mode to %s, current mode is %s", hvac_mode, self.hvac_mode)
        if self.hvac_mode == hvac_mode:
            # Do nothing if mode is same
            _LOGGER.debug(f"{self.name} is asked for mode {hvac_mode}, but it is already in {self.hvac_mode}. Do "
                          f"nothing.")
            pass
        elif hvac_mode == HVAC_MODE_OFF:
            # Keep last mode while turning off. May be used while calling climate turn_on service
            self._last_mode = self.hvac_mode
            await self._async_set_state(is_on=False)

        elif hvac_mode == HVAC_MODE_HEAT:
            saved_target_temp = self.target_temperature
            try:
                await self._tion_entry.connect()
                await self._async_set_state(heater=True, is_on=True)
                if self.hvac_mode == HVAC_MODE_FAN_ONLY:
                    await self.async_set_temperature(**{ATTR_TEMPERATURE: saved_target_temp})
            finally:
                await self._tion_entry.disconnect()
        elif hvac_mode == HVAC_MODE_FAN_ONLY:
            await self._async_set_state(heater=False, is_on=True)

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
            await self._tion_entry.connect()
            for a in actions:
                await a[0](**a[1])
            self._preset = preset_mode
            await self._async_update_state()
        finally:
            await self._tion_entry.disconnect()

    @property
    def boost_fan_mode(self) -> int:
        """Fan speed for boost mode

        :return: maximum of supported fan_modes
        """
        return max([int(x) for x in self.fan_modes])

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
        return self._tion_entry.mac

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._tion_entry.name

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        if self._keep_alive:
            async_track_time_interval(self.hass, self._async_update_state, self._keep_alive)
        await self._async_update_state(force=True)

    async def async_set_fan_mode(self, fan_mode):
        if self.preset_mode == PRESET_SLEEP:
            if int(fan_mode) > self.sleep_max_fan_mode:
                _LOGGER.info("Fan speed %s was required, but I'm in SLEEP mode, so it should not be greater than %d",
                             self.sleep_max_fan_mode)
                fan_mode = self.sleep_max_fan_mode

        if (self.preset_mode == PRESET_BOOST and self._is_boost) and fan_mode != self.boost_fan_mode:
            _LOGGER.debug("I'm in boost mode. Will ignore requested fan speed %s" % fan_mode)
            fan_mode = self.boost_fan_mode
        if fan_mode != self.fan_mode or not self._tion_entry.data.get("is_on"):
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

    @property
    def icon(self):
        return 'mdi:air-purifier'

    async def async_turn_on(self):
        """
        Turn breezer on. Tries to restore last state. Use HEAT as backup
        """
        _LOGGER.debug(f"Turning on from {self.hvac_mode} to {self._last_mode}")
        if self.hvac_mode != HVAC_MODE_OFF:
            # do nothing if we already working
            pass
        elif self._last_mode is None:
            await self.async_set_hvac_mode(HVAC_MODE_HEAT)
        else:
            await self.async_set_hvac_mode(self._last_mode)

    async def async_turn_off(self):
        _LOGGER.debug(f"Turning off from {self.hvac_mode}")
        await self.async_set_hvac_mode(HVAC_MODE_OFF)

    @property
    def fan_mode(self):
        return self._tion_entry.data.get("fan_speed")

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._tion_entry.data.get("heater_temp")

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._tion_entry.data.get("out_temp")

    async def _async_set_state(self, **kwargs):
        await self._tion_entry.set(**kwargs)
        self.async_write_ha_state()

    async def _async_update_state(self, time=None, force: bool = False, keep_connection: bool = False) -> None:
        """called every self._keep_alive"""
        await self._tion_entry.async_update_state(time, force, keep_connection)
        if self.fan_mode != self.boost_fan_mode and (self._is_boost or self.preset_mode == PRESET_BOOST):
            _LOGGER.warning(f"I'm in boost mode, but current speed {self.fan_mode} is not equal boost speed "
                            f"{self.boost_fan_mode}. Dropping boost mode")
            self._is_boost = False
            self._preset = PRESET_NONE

        self.async_write_ha_state()

    @property
    def device_info(self):
        return self._tion_entry.device_info

    @property
    def extra_state_attributes(self):
        attributes = {
            'air_mode': self._tion_entry.data.get("air_mode"),
            'in_temp': self._tion_entry.data.get("in_temp")
        }
        return attributes
