"""
Sensors for Tion breezers
"""
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntityDescription, SensorDeviceClass, SensorStateClass, SensorEntity
from homeassistant.const import TEMP_CELSIUS
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
        entity_category=EntityCategory.DIAGNOSTIC,
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


class TionSensor(SensorEntity, CoordinatorEntity):
    """Representation of a sensor."""

    def __init__(self, description: SensorEntityDescription, instance: TionInstance):
        """Initialize the sensor."""

        CoordinatorEntity.__init__(
            self=self,
            coordinator=instance,
        )
        self.entity_description = description
        self._attr_name = f"{instance.name} {description.name}"
        self._attr_device_info = instance.device_info
        self._attr_unique_id = f"{instance.unique_id}-{description.key}"

        _LOGGER.debug(f"Init of sensor {self.name} ({instance.unique_id})")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get(self.entity_description.key)

    def _handle_coordinator_update(self) -> None:
        self._attr_assumed_state = False if self.coordinator.last_update_success else True
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True
