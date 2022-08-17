"""
Fan controls for Tion breezers
"""
from __future__ import annotations

import logging
from datetime import timedelta
from functools import cached_property
from typing import Any

from homeassistant.components.climate.const import PRESET_BOOST, PRESET_NONE
from homeassistant.components.fan import FanEntityDescription, FanEntity, DIRECTION_FORWARD, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TionInstance
from .climate import TionClimateEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

config = FanEntityDescription(
    key="fan_speed",
    name="fan speed",
    entity_registry_enabled_default=True,
    icon="mdi:fan",
)


async def async_setup_entry(hass: HomeAssistant, _config: ConfigEntry, async_add_entities):
    """Set up the sensor entry"""

    async_add_entities([TionFan(config, hass.data[DOMAIN][_config.unique_id], hass)])
    return True


class TionFan(FanEntity, CoordinatorEntity):
    _attr_supported_features = FanEntityFeature.PRESET_MODE | FanEntityFeature.SET_SPEED
    _attr_oscillating = False
    _attr_preset_modes = [PRESET_NONE, PRESET_BOOST]
    _attr_speed_count = len(TionClimateEntity.attr_fan_modes())
    _attr_current_direction = DIRECTION_FORWARD
    _mode_percent_mapping = {
        0: 0,
        1: 17,
        2: 33,
        3: 50,
        4: 67,
        5: 83,
        6: 100,
    }
    _percent_mode_mapping = {
        0: 0,
        16: 1,
        33: 2,
        50: 3,
        66: 4,
        83: 5,
        100: 6,
    }
    # Home Assistant is using float speed step and ceil to determinate supported speed percents.

    def set_preset_mode(self, preset_mode: str) -> None:
        pass

    def set_direction(self, direction: str) -> None:
        raise NotImplemented

    def turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs) -> None:
        raise NotImplemented

    def oscillate(self, oscillating: bool) -> None:
        raise NotImplemented

    def turn_off(self, **kwargs: Any) -> None:
        pass

    def set_percentage(self, percentage: int) -> None:
        raise NotImplemented

    def __init__(self, description: FanEntityDescription, instance: TionInstance, hass: HomeAssistant):
        """Initialize the fan."""

        CoordinatorEntity.__init__(self=self, coordinator=instance, )
        self.entity_description = description
        self._attr_name = f"{instance.name} {description.name}"
        self._attr_device_info = instance.device_info
        self._attr_unique_id = f"{instance.unique_id}-{description.key}"
        self._saved_fan_mode = None

        _LOGGER.debug(f"Init of fan  {self.name} ({instance.unique_id})")
        _LOGGER.debug(f"Speed step is {self.percentage_step}")

        registry = async_get_entity_registry(hass=hass)
        entity = registry.async_get_or_create(
            domain=Platform.FAN,
            platform=DOMAIN,
            unique_id=self.unique_id,
        )
        _LOGGER.debug(f"{entity.entity_category=}, {entity.entity_id=}, {entity.options=} {entity.unique_id=}")
        if entity.entity_category == EntityCategory.CONFIG:
            import attr  # pylint: disable=import-outside-toplevel

            _LOGGER.debug(f"Updating {entity.entity_category=} for {entity.entity_id=}")
            new_value = {"entity_category": None}
            registry.entities[entity.entity_id] = attr.evolve(registry.entities[entity.entity_id], **new_value)
            registry.async_schedule_save()

    def percent2mode(self, percentage: int) -> int:
        result = 0
        try:
            return self._percent_mode_mapping[percentage]
        except KeyError:
            _LOGGER.warning(f"Could not to convert {percentage} to mode with {self._percent_mode_mapping}. "
                            f"Will use fall back method.")
            for i in range(len(TionClimateEntity.attr_fan_modes())):
                if percentage < self.percentage_step * i:
                    break
                else:
                    result = i
            else:
                result = 6

            return result

    def mode2percent(self) -> int | None:
        return self._mode_percent_mapping[self.fan_mode] if self.fan_mode is not None else None

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        await self.coordinator.set(fan_speed=self.percent2mode(percentage), is_on=percentage > 0)

    @cached_property
    def boost_fan_mode(self) -> int:
        return max(TionClimateEntity.attr_fan_modes())

    @property
    def fan_mode(self):
        return self.coordinator.data.get(self.entity_description.key)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_BOOST and self.preset_mode != PRESET_BOOST:
            if self._saved_fan_mode is None:
                self._saved_fan_mode = int(self.fan_mode)

            await self.coordinator.set(fan_speed=self.boost_fan_mode)
        if preset_mode == PRESET_NONE and self.preset_mode == PRESET_BOOST:
            if self._saved_fan_mode is not None:
                await self.coordinator.set(fan_speed=self._saved_fan_mode)
                self._saved_fan_mode = None

        self._attr_preset_mode = preset_mode

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs, ) -> None:
        target_speed = 2 if self._saved_fan_mode is None else self._saved_fan_mode
        self._saved_fan_mode = None
        await self.coordinator.set(fan_speed=target_speed, is_on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._saved_fan_mode is None and self.fan_mode > 0:
            self._saved_fan_mode = self.fan_mode

        await self.coordinator.set(is_on=False)

    def _handle_coordinator_update(self) -> None:
        self._attr_assumed_state = False if self.coordinator.last_update_success else True
        self._attr_is_on = self.coordinator.data.get("is_on")
        self._attr_percentage = self.mode2percent() if self._attr_is_on else 0  # should check attr to avoid deadlock
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True
