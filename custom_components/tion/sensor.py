"""
Sensors for Tion breezers
"""
import logging
import datetime
from typing import List

from homeassistant.const import TEMP_CELSIUS
from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, TION_SENSORS

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    _LOGGER.critical("Sensors configuration via configuration.yaml is not supported!")
    return False


async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, add_entities):
    """Set up the sensor entry"""
    sensors = []
    for s in TION_SENSORS.keys():
        sensors.append(TionSensor(hass, s, config.entry_id))

    add_entities(sensors)
    return True


class TionSensor(Entity):
    """Representation of a sensor."""

    def __init__(self, hass: HomeAssistant, sensor_type: str, entry_id):
        """Initialize the sensor."""
        if sensor_type not in TION_SENSORS.keys():
            raise NotImplementedError('Sensor "%s" is not supported' % sensor_type)
        self.hass: HomeAssistant = hass
        self._sensor_type = sensor_type
        self._entry_id = entry_id
        self._state = None
        self.hass = hass

        _LOGGER.info("Init of sensor %s for %s (%s) " % (
            sensor_type, entry_id, self.hass.data[DOMAIN][self._entry_id].name
        ))

    @property
    def name(self):
        """Return the name of the sensor."""
        return self.hass.data[DOMAIN][self._entry_id].name + ' ' + self._sensor_type

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._sensor_type == 'input temperature':
            return self.hass.data[DOMAIN][self._entry_id].in_temp
        elif self._sensor_type == 'filters remain':
            return self.hass.data[DOMAIN][self._entry_id].filter_remain

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS if self._sensor_type == 'input temperature' else None

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {}

    async def _async_update(self, time=None):
        """Fetch new state data for the sensor.
        This is the only method that should fetch new data for Home Assistant.
        """      
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        async_track_time_interval(
            self.hass, self._async_update, datetime.timedelta(seconds=self.hass.data[DOMAIN][self._entry_id].keep_alive/2)
        )
        await self._async_update()

    @property
    def unique_id(self):
        return self.name + " " + self._sensor_type
