"""Adds support for generic thermostat units."""
import asyncio
import logging
from bluepy import btle
from typing import Tuple, Callable

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_PRESET_MODE,
    ATTR_FAN_MODES,
    ATTR_FAN_MODE,
    CURRENT_HVAC_FAN,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_OFF,
    HVAC_MODE_HEAT,
    HVAC_MODE_FAN_ONLY,
    HVAC_MODE_OFF,
    PRESET_AWAY,
    PRESET_NONE,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_FAN_MODE,
    SUPPORT_PRESET_MODE,
 )
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    EVENT_HOMEASSISTANT_START,
    PRECISION_WHOLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import DOMAIN as HA_DOMAIN, callback
from homeassistant.helpers import condition
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Tion Breezer"

CONF_TARGET_TEMP = "target_temp"
CONF_KEEP_ALIVE = "keep_alive"
CONF_INITIAL_HVAC_MODE = "initial_hvac_mode"
CONF_AWAY_TEMP = "away_temp"
CONF_MAC = "mac"
SUPPORTED_DEVICES = ['S3']
SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE

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


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the generic thermostat platform."""
    async_add_entities(
        [
            Tion(
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

class TionException(Exception):
    def __init__(self, expression, message):
        self.expression = expression
        self.message = message

class Tion(ClimateEntity, RestoreEntity):
    """Representation of a Tion device."""
    uuid = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
    uuid_write = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
    uuid_notify = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
    write = None
    notify = None
    _commands = {
        "prefix": 61,
        "suffix": 90,
        "REQUEST_PARAMS": 1,
        "SET_PARAMS": 2
    }

    def __init__(
            self,
            name,
            mac,
            target_temp,
            keep_alive,
            initial_hvac_mode,
            away_temp,
            unit,
    ):
        """Initialize the thermostat."""
        #General part
        self._name = name

        self._keep_alive = keep_alive
        self._hvac_mode = initial_hvac_mode
        self._last_mode = self._hvac_mode
        self._saved_target_temp = target_temp or away_temp
        self._is_on = False
        self._heater = False
        self._cur_temp = None
        self._temp_lock = asyncio.Lock()
        self._target_temp = target_temp
        self._unit = unit
        self._support_flags = SUPPORT_FLAGS
        if away_temp:
            self._support_flags = SUPPORT_FLAGS | SUPPORT_PRESET_MODE
        self._away_temp = away_temp
        self._is_away = False
        self._hvac_mapping = {
            HVAC_MODE_HEAT: CURRENT_HVAC_HEAT, #heater is on. We may heat or not, so it is a hack
            HVAC_MODE_FAN_ONLY: CURRENT_HVAC_FAN, #heater is off
            HVAC_MODE_OFF: CURRENT_HVAC_OFF #device is off
        }
        self._hvac_list = list(self._hvac_mapping.keys())
        self._fan_speed = 1
        #tion part
        self._btle = btle.Peripheral(None)
        self._mac = mac



    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        if self._keep_alive:
            async_track_time_interval(
                self.hass, self._async_update_state, self._keep_alive
            )
        await self._async_update_state(force=True)



        @callback
        def _async_startup(event):
            """Init on startup."""

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

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
            if old_state.attributes.get(ATTR_PRESET_MODE) == PRESET_AWAY:
                self._is_away = True
            if not self._hvac_mode and old_state.state:
                self._hvac_mode = old_state.state

        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                self._target_temp = self.target_temp

            _LOGGER.warning(
                "No previously saved temperature, setting to %s", self._target_temp
            )

        # Set default state to off
        if not self._hvac_mode:
            self._hvac_mode = HVAC_MODE_OFF



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
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.
        Need to be one of CURRENT_HVAC_*.
        """
        try:
            current_hvac_operation = self._hvac_mapping[self._hvac_mode]
        except KeyError as e:
            current_hvac_operation = CURRENT_HVAC_OFF
        return current_hvac_operation

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp



    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp."""
        return PRESET_AWAY if self._is_away else PRESET_NONE

    @property
    def preset_modes(self):
        """Return a list of available preset modes or PRESET_NONE if _away_temp is undefined."""
        return [PRESET_NONE, PRESET_AWAY] if self._away_temp else PRESET_NONE

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        _LOGGER.warning("Need to set mode to " + hvac_mode)
        if hvac_mode == self._hvac_mode:
            if hvac_mode == HVAC_MODE_HEAT:
                hvac_mode = HVAC_MODE_FAN_ONLY
            elif hvac_mode == HVAC_MODE_OFF:
                try:
                    hvac_mode = self._last_mode
                except AttributeError:
                    hvac_mode = HVAC_MODE_FAN_ONLY

        if hvac_mode == HVAC_MODE_HEAT:
            await self._async_set_state(heater=True, is_on=True)
        elif hvac_mode == HVAC_MODE_FAN_ONLY:
            await self._async_set_state(heater=False, is_on=True)
        elif hvac_mode == HVAC_MODE_OFF:
            self._last_mode = self._hvac_mode
            await self._async_set_state(is_on=False)
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        self._hvac_mode = hvac_mode
        # Ensure we update the current operation after changing the mode
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
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new preset mode."""
        if preset_mode == PRESET_AWAY and not self._is_away:
            self._is_away = True
            self._saved_target_temp = self._target_temp
            self._target_temp = self._away_temp
            await self._async_set_state(heater_temp=self._target_temp)
        elif preset_mode == PRESET_NONE and self._is_away:
            self._is_away = False
            self._target_temp = self._saved_target_temp
            await self._async_set_state(heater_temp=self._target_temp)

        self.async_write_ha_state()
    @property
    def fan_mode(self):
        return self._fan_speed

    @property
    def fan_modes(self):
        return [1,2,3,4,5,6]

    @property
    def precision(self):
        """Return the precision of the system."""
        return PRECISION_WHOLE

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 1

    async def async_set_fan_mode(self, fan_mode):
        await self._async_set_state(fan_speed=fan_mode, is_on=True)

    def _connect(self):
        try:
            connection_status = self._btle.getState()
        except btle.BTLEInternalError as e:
            if str(e) == "Helper not started (did you call connect()?)":
                connection_status = "disc"
            else:
                _LOGGER.error("Got exception '" + str(e) + "'")
                raise e
        except BrokenPipeError as e:
            connection_status = "disc"
            self._btle = btle.Peripheral(None)
            _LOGGER.error("Got exception '" + str(e) + "'")

        if connection_status == "disc":
            self._btle.connect(self._mac, btle.ADDR_TYPE_RANDOM)
            for tc in self._btle.getCharacteristics():
                if tc.uuid == self.uuid_notify:
                    self.notify = tc
                if tc.uuid == self.uuid_write:
                    self.write = tc

    def _do_action(self, action: Callable, max_tries: int = 3, *args, **kwargs):
        tries: int = 0
        response = None

        while tries < max_tries:
            _LOGGER.debug("Doing " + action.__name__ + ". Attempt " + str(tries+1) + "/" + str(max_tries))
            try:
                if action.__name__ != '_connect':
                    self._connect()

                response = action(*args, **kwargs)
                break
            except Exception as e:
                tries += 1
                _LOGGER.warning("Got exception while " + action.__name__ + ": " + str(e))
                pass
        else:
            if action.__name__ == '_connect':
                message = "Could not connect to " + self._mac
            elif action.__name__ == '__try_notify_read':
                message = "Could not read from " + str(self.notify.uuid)
            elif action.__name__ == '__try_write':
                message = "Could not write request + " + kwargs['request'].hex()
            elif action.__name__ == '__try_get_state':
                message = "Could not get updated state"
            else: message = "Could not do " + action.__name__

            raise TionException(action.__name__, message)

        return response

    def create_command(self, command: int) -> bytearray:
        return bytearray([
            self._commands['prefix'], command, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,self._commands['suffix']
        ])

    def _get_status_command(self) -> bytearray:
        return self.create_command(self._commands['REQUEST_PARAMS'])

    def _decode_response(self, response: bytearray) -> dict:
        def _process_status(code: int) -> bool:
            return True if code == 1 else False

        def _process_mode(mode_code: int) -> str:
            modes = [ 'recirculation', 'mixed', 'street' ]
            mode = 'street'
            try:
                mode = modes[mode_code]
            except IndexError:
                pass
            return mode

        result = {}
        try:
            result = {
                "heater": _process_status(response[4] & 1),
                "is_on": _process_status(response[4] >> 1 & 1),
                "sound": _process_status(response[4] >> 3 & 1),
                "mode": _process_mode(int(list("{:02x}".format(response[2]))[0])),
                "fan_speed": int(list("{:02x}".format(response[2]))[1]),
                "heater_temp": response[3],
                "in_temp": response[8],
                "out_temp": response[7],
                "filter_remain": response[10] * 256 + response[9],
                "time": "{}:{}".format(response[11], response[12]),
                "request_error_code": response[13],
                "fw_version": "{:02x}{:02x}".format(response[16], response[17])
            }
        except IndexError as e:
            result = {
                "error": "Got bad response from Tion '%s': %s while parsing" % (response, str(e))
            }
        finally:
            return result

    def __try_notify_read(self): return self.notify.read()
    def __try_write(self, request: bytearray): return self.write.write(request)
    def __try_get_state(self) -> bytearray: return self._btle.getServiceByUUID(self.uuid).getCharacteristics()[0].read()

    async def _async_update_state(self, time=None, force: bool = False, keep_connection: bool = False) -> dict:
        _LOGGER.debug("Update fired force = " + str(force) + ". Keep connection is " + str(keep_connection))
        response = {}
        try:
            self._do_action(self._connect)
            self._do_action(self.__try_notify_read)
            self._do_action(self.__try_write, request=self._get_status_command())
            response = self._do_action(self.__try_get_state)

            _LOGGER.debug("Got response from device: " + response.hex())
            response = self._decode_response(response)
            self._cur_temp = response["out_temp"]
            self._target_temp = response["heater_temp"]
            self._is_on = response["is_on"]
            self._heater = response["heater"]
            self._fan_speed = response["fan_speed"]
            self.async_write_ha_state()

        except TionException as e:
            _LOGGER.error(str(e))

        finally:
            if not keep_connection:
                self._btle.disconnect()

        return response

    async def _async_set_state(self, **kwargs):
        def _encode_status(status: bool) -> int:
            return 1 if status else 0

        def _encode_mode(mode: str) -> int:
            modes = ['recirculation', 'mixed', 'street']
            return modes.index(mode) if mode in modes else 2

        args = ', '.join('%s=%r' % x for x in kwargs.items())
        _LOGGER.info("Need to set: " + args)

        current_settings = await self._async_update_state(force=True, keep_connection=True)
        if bool(current_settings):
            settings = {**current_settings, **kwargs}

            new_settings = self.create_command(self._commands['SET_PARAMS'])
            new_settings[2] = int(settings["fan_speed"])
            new_settings[3] = int(settings["heater_temp"])
            new_settings[4] = _encode_mode(settings["mode"])
            new_settings[5] = _encode_status(settings["heater"]) | (_encode_status(settings["is_on"]) << 1) | (
                    _encode_status(settings["sound"]) << 3)

            self.notify.read()
            self.write.write(new_settings)
            await self._async_update_state(force=True, keep_connection=True)
            self._btle.disconnect()
            self.async_write_ha_state()
        else:
            _LOGGER.error("Got empty response from _async_update_state")
