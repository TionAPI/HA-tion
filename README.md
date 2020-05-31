# Custom integration for Tion S3 breezer for Home Assistant
This custom integration will allow your Home assistant to control:
* fan speed
* target heater temp
* heater mode (on/off)
for your Tion S3 breezer.

:warning: Please remember that breezer is not heating device and don't try use it for room heating :warning: 
#### disclaimer: everything that you do, you do at your own peril and risk

# How to use
## Requirements
  1. BTLE supported host with Home Assistant
  1. Tion S3 breezer
## Prepare
Before using this custom component you must pair you breezer and homeassistant host.
Ordinary bluetooth pairing is not enough. Please see 
  [python repository](https://github.com/TionAPI/python) for pairing procedure description
## Installation
### shell
```shell script
cd <homeassist_config_directory>
mkdir -p custom_components
cd custom_components
git clone https://github.com/TionAPI/HA-tion.git
ln -s HA-tion.git/custom_components/tion tion 
```
## Configuration
configuration.yaml:
```yaml
climate:
  - platform: tion
    mac: <put:MAC:here>   #tion MAC address, like in pair
    target_temp: 23       #default heater temp 
    away_temp: 15         #heater temp in away mode
```
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
    custom_components.tion.climate: debug
```
