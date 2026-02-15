# Aerostar HACS Component

[![Install](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=BR0kEN-&repository=ha-aerostar&category=integration)

## Recuperator Efficacy Sensor

- State class: `Measurement`
- Unit of measurement: `%`
- Device: `select yours`

```yaml
{% set unit_id = 'aerostar_ecostar_500_ec_x' %}
{% set supply = states('sensor.'~unit_id~'_supply_temperature') | float(none) %}
{% set exhaust = states('sensor.'~unit_id~'_exhaust_temperature') | float(none) %}
{% set outside = states('sensor.'~unit_id~'_outdoor_temperature') | float(none) %}

{% if supply is none or exhaust is none or outside is none %}
  unknown
{% else %}
  {% set denom = (exhaust - outside) | abs %}
  {% if denom < 0.2 %}
    unknown
  {% else %}
    {{ [0, [((supply - outside) | abs / denom * 100), 100] | min] | max | round(1) }}
  {% endif %}
{% endif %}
```

## Screenshots

![Climate](docs/images/1-climate.jpg)
![Device](docs/images/2-device.jpg)
