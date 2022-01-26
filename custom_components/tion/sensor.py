"""
Sensors for Tion breezers
"""
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntityDescription, SensorDeviceClass, SensorStateClass, SensorEntity
from homeassistant.const import TEMP_CELSIUS
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import TionInstance
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="in_temp",
        name="input temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    SensorEntityDescription(
        key="out_temp",
        name="output temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    SensorEntityDescription(
        key="filter_remain",
        name="filters remain",
        entity_registry_enabled_default=True,
        entity_category="diagnostic",
    ),
)


async def async_setup_platform(_hass: HomeAssistant, _config, _async_add_entities, _discovery_info=None):
    _LOGGER.critical("Sensors configuration via configuration.yaml is not supported!")
    return False


async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities):
    """Set up the sensor entry"""
    tion_instance = hass.data[DOMAIN][config.unique_id]
    entities: list[TionSensor] = [
        TionSensor(description, tion_instance) for description in SENSOR_TYPES]
    async_add_entities(entities)

    return True


class TionSensor(SensorEntity):
    """Representation of a sensor."""

    def __init__(self, description: SensorEntityDescription, instance: TionInstance):
        """Initialize the sensor."""

        self.entity_description = description
        self._tion_instance: TionInstance = instance
        self._attr_name = f"{instance.name} {description.name}"
        self._attr_device_info = instance.device_info
        self._attr_unique_id = f"{instance.unique_id}-{description.key}"

        _LOGGER.debug(f"Init of sensor {self.name} ({instance.unique_id})")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._tion_instance.data.get(self.entity_description.key)
