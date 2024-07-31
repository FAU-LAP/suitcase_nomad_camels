# suitcase.nomad_camels_hdf5

This is a suitcase subpackage for the hdf5 Output of NOMAD CAMELS.

## Installation

```
pip install suitcase-nomad-camels-hdf5
```



# Changelog

## 0.2.1
Fixed bug with fits

## 0.2.0
Features:
- Added virtual datasets of measured data in instruments, resembling the NeXus standard more closely.
- More metadata for measured channels.

Fixes:
- Now correctly saving the variable signal also after run.


## 0.1.4
Fixed saving of string data.

## 0.1.3
Fixes:
- Fixed issue with empty data, this is now caught.
- can now save named tuples as they come from ophyd devices or camel's variable signal

## 0.1.2
Fixed issue with dots in paths

## 0.1.1
Added CAMELS plots to export function

## 0.1.0
Initial release
