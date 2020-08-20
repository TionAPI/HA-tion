"""The Tion breezer component."""
import logging
from .const import DOMAIN
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass, config_entry: ConfigEntry):
    _LOGGER.info("Setting up %s ", config_entry.unique_id)

    config = {}
    if hasattr(config_entry, 'options'):
        if any(config_entry.options):
            config = config_entry.options
    if not any(config):
        if hasattr(self._config_entry, 'data'):
            if any(self._config_entry.data):
                config = self._config_entry.data

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][config_entry.entry_id] = TionInstance(hass, config_entry, config)
    return True


class TionInstance:
    def __init__(self, hass, config_entry, conf):
        self.hass = hass
        self.config_entry = config_entry
        self.entry_id = self.config_entry.entry_id
        self.conf = conf
        hass.loop.create_task(self.start_up())

    async def start_up(self):
        _LOGGER.info('Going setup climate platform')
        await self.hass.config_entries.async_forward_entry_setup(self.config_entry, 'climate')
        _LOGGER.info('Done')
