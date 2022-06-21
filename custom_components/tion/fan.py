"""
Fan controls for Tion breezers
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta
from functools import cached_property
from typing import Any, Optional

from homeassistant.components.climate.const import PRESET_BOOST, PRESET_NONE
from homeassistant.components.fan import FanEntityDescription, FanEntity, SUPPORT_SET_SPEED, SUPPORT_PRESET_MODE, \
    DIRECTION_FORWARD
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import int_states_in_range, ranged_value_to_percentage, percentage_to_ranged_value

from . import TionInstance
from .climate import TionClimateEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

config = FanEntityDescription(
    key="fan_speed",
    entity_category=EntityCategory.CONFIG,
    name="fan speed",
    entity_registry_enabled_default=True,
    icon="mdi:fan",
)


async def async_setup_entry(hass: HomeAssistant, _config: ConfigEntry, async_add_entities):
    """Set up the sensor entry"""

    async_add_entities([TionFan(config, hass.data[DOMAIN][_config.unique_id])])
    return True


class TionFan(FanEntity, CoordinatorEntity):
    _attr_supported_features = SUPPORT_PRESET_MODE | SUPPORT_SET_SPEED
    _attr_oscillating = False
    _attr_preset_modes = [PRESET_NONE, PRESET_BOOST]
    _attr_speed_count = len(TionClimateEntity.attr_fan_modes())
    _attr_current_direction = DIRECTION_FORWARD
    _SPEEDS = (0, 6)

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

    def __init__(self, description: FanEntityDescription, instance: TionInstance):
        """Initialize the fan."""

        CoordinatorEntity.__init__(self=self, coordinator=instance, )
        self.entity_description = description
        self._attr_name = f"{instance.name} {description.name}"
        self._attr_device_info = instance.device_info
        self._attr_unique_id = f"{instance.unique_id}-{description.key}"
        self._saved_fan_mode = None

        _LOGGER.debug(f"Init of fan  {self.name} ({instance.unique_id})")
        _LOGGER.debug(f"Speed step is {self.percentage_step}")

    @property
    def percentage(self) -> Optional[int]:
        """Return the current speed percentage."""
        return ranged_value_to_percentage(self._SPEEDS, self.fan_mode) if self.coordinator.data.get("is_on") else 0

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return int_states_in_range(self._SPEEDS)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        await self.coordinator.set(fan_speed=math.ceil(percentage_to_ranged_value(self._SPEEDS, percentage)),
                                   is_on=percentage > 0)

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
        self.async_write_ha_state()
