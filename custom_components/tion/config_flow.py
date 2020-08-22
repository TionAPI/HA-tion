"""Adds config flow for Tion custom component."""
import asyncio
import os
import logging
import datetime

import voluptuous as vol
from voluptuous import Schema
from homeassistant import data_entry_flow

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.util.json import load_json
from homeassistant.core import callback

from .const import DOMAIN, TION_SCHEMA, CONF_KEEP_ALIVE

_LOGGER = logging.getLogger(__name__)


class TionFlow:
    def __init__(self):
        self._schema = vol.Schema({})
        self._data: dict = {}
        self._config_entry: ConfigEntry = {}

    @staticmethod
    def __get_my_platform(config: dict):
        for i in config:
            if i['platform'] == DOMAIN:
                return i

    @staticmethod
    def __add_default_value(config: dict, key: str) -> dict:
        result = {}
        if key in config:
            if key == 'pair':
                # don't suggest pairing if device already configured
                result['default'] = False
            else:
                result['default'] = config[key]
        elif 'default' in TION_SCHEMA[key].keys():
            result['default'] = TION_SCHEMA[key]['default']

        return result

    @staticmethod
    def __add_value_from_yaml_config(config: dict, key: str) -> dict:
        result = {}
        try:
            value = config[key].seconds if isinstance(config[key], datetime.timedelta) else config[key]
            result['description'] = {"suggested_value": value}
        except (TypeError, KeyError) as e:
            # TypeError -- config is not dict (have no climate in config, for example)
            # KeyError -- config have no key (have climate, but have no Tion)
            _LOGGER.debug(e)
            pass

        return result
        
    def __add_value_from_saved_settings(self, config: dict, key: str) -> dict:
        return self.__add_value_from_yaml_config(config, key)
      
    def _build_schema(self, config: dict) -> None:
        config = self.__get_my_platform(config)

        for k in TION_SCHEMA.keys():
            type = vol.Required if TION_SCHEMA[k]['required'] else vol.Optional
            options = {}
            options.update(self.__add_default_value(self.config, k))
            options.update(self.__add_value_from_yaml_config(config, k))
            options.update(self.__add_value_from_saved_settings(self.config, k))
            self._schema = self._schema.extend({type(k, **options): TION_SCHEMA[k]['type']})

    async def async_step_user(self, input):
        """user initiates a flow via the user interface."""

        if input is not None:
            self._data = input
            if input['pair']:
                return self.async_show_form(step_id="pair")
            else:
                _LOGGER.debug("Going create entry with name %s" % input['name'])
                _LOGGER.debug(input)
                return self.async_create_entry(title=input['name'], data=input)

        self._build_schema(self.hass.data['climate'].config['climate'])
        return self.async_show_form(step_id="user", data_schema=self._schema)

    async def async_step_pair(self, input):
        """Pair host and breezer"""
        from tion_btle import s3 as tion
        _tion = tion(mac)
        _tion.pair()
        return self.async_create_entry(title=self._data['name'], data=self._data)

    @property
    def config(self) -> dict:
        config = {}
        if hasattr(self._config_entry, 'options'):
            if any(self._config_entry.options):
                config = self._config_entry.options
        if not any(config):
            if hasattr(self._config_entry, 'data'):
                if any(self._config_entry.data):
                    config = self._config_entry.data

        return config


@config_entries.HANDLERS.register(DOMAIN)
class TionConfigFlow(TionFlow, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        super().__init__()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TionOptionsFlowHandler(config_entry)


class TionOptionsFlowHandler(TionFlow, config_entries.OptionsFlow):

    def __init__(self, config_entry):
        """Initialize Shelly options flow."""
        super().__init__()
        self._config_entry = config_entry
        self._entry_id = config_entry.entry_id

        # config_entry.add_update_listener(update_listener)

    async def async_step_init(self, input=None):
        return await self.async_step_user(input)
