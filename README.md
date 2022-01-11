![version_badge](https://img.shields.io/badge/minimum%20HA%20version-2021.12-red)
# Custom integration for Tion S3, S4 and Lite breezers for Home Assistant
This custom integration will allow your Home assistant to control:
* fan speed
* target heater temp
* heater mode (on/off)
* some presets:
    * boost
    * away    

of your Tion S3/S4/Lite breezer via bluetooth. If you are prefer control breezer via Magic Air, please follow to https://github.com/airens/tion_home_assistant repository.

:warning: Please remember that breezer is not heating device and don't try use it for room heating :warning: 
#### disclaimer: everything that you do, you do at your own peril and risk

# How to use
## Requirements
  1. BTLE supported host with Home Assistant
  1. Tion S3, S4 or Lite breezer

## Installation & configuration
### HACS installation
  1. goto HACS->Integrations->three dot at upper-right conner->Custom repositories;
  1. add TionAPI/HA-tion to ADD CUSTOM REPOSITORY field and select Integration in CATEGORY; 
  1. click "add" button;
  1. find "Tion breezer" integration;
  1. click "Install". Home assistant restart may be required;
  
### Configuration via User interface
  1. go to Integrations page;
  1. click "plus" button;
  1. type "Tion" in search field;
  1. click on "Tion breezer integration";
  1. fill fields;
  1. click "Next" and follow instructions;  
  1. restart Home Assistant.
  
  Repeat this steps for every device that you are going to use with home assistant.

## Usage 
### Turning on / Turning off
* calling `climate.set_hvac_mode`. Mode:
  * `off` will turn off breezer;
  * `fan_only` will turn brezzer on with turned off heater
  * `heat` will turn breezer on with tunrned on heater
  fan speed will not be changed.
* calling `climate.set_fan_mode`. 
  * `0` will turn off breezer;
  * `1`..`6` will turn breezer on.
  No state (`heater`/`fan_only`) will be changed.
* ![added_in_version_badge](https://img.shields.io/badge/Since-v2.1.3-red) you may use `climate.turn_on` and `climate.turn_off` services. `climate.turn_on` will turn on breezer into the state it was before being turned off.  

### Automation example
automations.yaml:
```yaml
- id: 'tion1'
  alias: 1 speed for tion by co2 < 500
  trigger:
  - platform: numeric_state
    entity_id: sensor.mhz19_co2
    below: '500'    
    for: 00:05:00    
  condition:
  - condition: not
    conditions:
    - condition: state
      entity_id: climate.tion_breezer
      state: 'off'
  action:
  - service: climate.set_fan_mode
    entity_id: climate.tion_breezer
    data:
      fan_mode: 1    
    
- id: 'tion4'
  alias: 4 speed for tion with co2 > 600
  trigger:
  - platform: numeric_state
    entity_id: sensor.mhz19_co2
    above: '600'    
    for: 00:05:00    
  condition:
  - condition: time     #don't turn on fan at speed 4 from 22:00 to 08:00 
    after: '08:00:00'
    before: '22:00:00'    
  - condition: not
    conditions:
    - condition: state
      entity_id: climate.tion_breezer
      state: 'off'
  action:
  - service: climate.set_fan_mode
    entity_id: climate.tion_breezer
    data:
      fan_mode: 4  
```
## Error reporting
Feel free to open issues.  
Please attach debug log to issue.  
For turning on debug  log level you may use following logger settings in configuration.yaml:
```yaml
logger:
  default: warning
  logs:
    custom_components.tion: debug
    tion_btle.tion: debug
    tion_btle.s3: debug
    tion_btle.lite: debug
    custom_components.tion.config_flow: debug
```
