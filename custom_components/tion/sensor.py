"""
Sensors for Tion breezers
"""
import logging
from datetime import timedelta

from homeassistant.const import TEMP_CELSIUS
from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import TionInstance
from .const import DOMAIN, TION_SENSORS

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


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
        self._tion_instance: TionInstance = self.hass.data[DOMAIN][self._entry_id]

        _LOGGER.info("Init of sensor %s for %s (%s) " % (
            sensor_type, entry_id, self.hass.data[DOMAIN][self._entry_id].name
        ))

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._tion_instance.name + ' ' + self._sensor_type

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._sensor_type == 'input temperature':
            return self._tion_instance.in_temp
        elif self._sensor_type == 'filters remain':
            return self._tion_instance.filter_remain

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS if self._sensor_type == 'input temperature' else None

    @property
    def should_poll(self):
        """Return the polling state."""
        return True

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {}

    @property
    def unique_id(self):
        return self.name + " " + self._sensor_type

    @property
    def device_info(self):
        return self._tion_instance.device_info
