"""Adds config flow for Tion custom component."""
from __future__ import annotations

import logging
import datetime
import time

import tion_btle
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, async_get_hass
from tion_btle.tion import Tion

from .const import DOMAIN, TION_SCHEMA, CONF_MAC

_LOGGER = logging.getLogger(__name__)

TION_OPTIONS_SCHEMA = TION_SCHEMA.copy()
del TION_OPTIONS_SCHEMA["pair"]
del TION_OPTIONS_SCHEMA[CONF_MAC]
del TION_OPTIONS_SCHEMA["model"]


class TionFlow:
    def __init__(self):
        self._data: dict = {}
        self._config_entry: ConfigEntry = {}
        self._retry: bool = False

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
    def __add_value_from_saved_settings(config: dict, key: str) -> dict:
        result = {}
        try:
            value = config[key].seconds if isinstance(config[key], datetime.timedelta) else config[key]
            result['description'] = {"suggested_value": value}
        except (TypeError, KeyError):
            # TypeError -- config is not dict (have no climate in config, for example)
            # KeyError -- config have no key (have climate, but have no Tion)
            pass

        return result

    def get_schema(self, schema_description: dict = None) -> vol.Schema:
        schema = vol.Schema({})
        if schema_description is None:
            schema_description = {}

        for k in schema_description.keys():
            type = vol.Required if TION_SCHEMA[k]['required'] else vol.Optional
            options = {}
            options.update(self.__add_default_value(self.config, k))
            options.update(self.__add_value_from_saved_settings(self.config, k))
            if self._retry:
                options.update(self.__add_value_from_saved_settings(self._data, k))
            schema = schema.extend({type(k, **options): TION_SCHEMA[k]['type']})
        return schema

    @property
    def config(self) -> dict:
        try:
            data = dict(self._config_entry.data or {})
        except AttributeError:
            data = {}

        try:
            options = self._config_entry.options or {}
            data.update(options)
        except AttributeError:
            pass
        return data

    @staticmethod
    def getTion(model: str, mac: str) -> tion_btle.TionS3 | tion_btle.TionLite | tion_btle.TionS4:

        btle_device = bluetooth.async_ble_device_from_address(hass=async_get_hass(), address=mac, connectable=True)
        if model == 'S3':
            from tion_btle.s3 import TionS3 as Breezer
        elif model == 'S4':
            from tion_btle.s4 import TionS4 as Breezer
        elif model == 'Lite':
            from tion_btle.lite import TionLite as Breezer
        else:
            raise NotImplementedError("Model '%s' is not supported!" % model)
        return Breezer(btle_device)


class TionConfigFlow(TionFlow, config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup."""
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        super().__init__()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TionOptionsFlowHandler(config_entry)

    async def _create_entry(self, data, title, step: str):
        if step in ["user", "pair"]:
            await self.async_set_unique_id(data["mac"])
            self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title, data=data)

    async def async_step_user(self, input=None):
        """user initiates a flow via the user interface."""

        if input is not None:
            result = {}
            self._data = input
            if input['pair']:
                _LOGGER.debug("Showing pair info")
                return self.async_show_form(step_id="pair")
            else:
                _LOGGER.debug("Going create entry with name %s" % input['name'])
                _LOGGER.debug(input)
                try:
                    _tion: Tion = self.getTion(input['model'], input['mac'])
                    result = _tion.get()
                except Exception as e:
                    _LOGGER.error("Could not get data from breezer. result is %s, error: %s" % (result, str(e)))
                    return self.async_show_form(step_id='add_failed')

                return await self._create_entry(title=input['name'], data=input, step="user")

        return self.async_show_form(step_id="user", data_schema=self.get_schema(TION_SCHEMA))

    async def async_step_pair(self, input):
        """Pair host and breezer"""
        _LOGGER.debug("Real pairing step")
        result = {}
        try:
            _LOGGER.debug(self._data)
            _tion: Tion = self.getTion(self._data['model'], self._data['mac'])
            await _tion.pair()
            # We should sleep a bit, because immediately connection will cause device disconnected exception while
            # enabling notifications
            time.sleep(3)

            result = await _tion.get()
        except Exception as e:
            _LOGGER.error("Cannot pair and get data. Data is %s, result is %s; %s: %s", self._data, result,
                          type(e).__name__, str(e))
            return self.async_show_form(step_id='pair_failed')

        return await self._create_entry(title=self._data['name'], data=self._data, step="pair")

    async def async_step_add_failed(self, input):
        _LOGGER.debug("Add failed. Returning to first step")
        self._retry = True
        return await self.async_step_user(None)

    async def async_step_pair_failed(self, input):
        _LOGGER.debug("Pair failed. Returning to first step")
        self._retry = True
        return await self.async_step_user(None)


class TionOptionsFlowHandler(TionConfigFlow, config_entries.OptionsFlow):
    """Change options dialog."""

    def __init__(self, config_entry):
        """Initialize Shelly options flow."""
        super().__init__()
        self._config_entry = config_entry
        self._entry_id = config_entry.entry_id

        # config_entry.add_update_listener(update_listener)

    async def async_step_init(self, input=None):
        if input is not None:
            return await self._create_entry(title="", data=input, step="options")
        else:
            return self.async_show_form(step_id="init", data_schema=self.get_schema(TION_OPTIONS_SCHEMA))
