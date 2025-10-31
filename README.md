# suitcase.nomad_camels_hdf5

This is a suitcase subpackage for the hdf5 Output of NOMAD CAMELS.

## Installation

```
pip install suitcase-nomad-camels-hdf5
```



# Changelog
### 1.2.0
Fixes:
- Fixed broken 2D plots
### 1.1.0
Fixes:
- Fixed broken resolving of aliases

### 1.0.0
Major restructuring of the way plots are added to the measurement data.
Now adds a `plot_n` where `n` is the number of the plot to each (nested) data group it was created in. This means plots of subprotocols are now where the subprotocol data is saved. Each plot (NXdata) entry contains the required x, y (and z) data. If it is simply a plot of a measured channel it is an HDF5 SoftLink. If it is contains an arithmetic operation like adding multiple channels or dividing the read data by some value, the newly calculated data is saved as a new dataset in the plot entry. This now enables users to immediately view every plot they defined in CAMELS directly in the HDF5 file.

### 0.8.0
Now correctly adds plot annotations to deeply nested plot data with the full path.

### 0.7.0
Compatible with more nested data structure of CAMELS 1.9.0

### 0.6.3
Cleaned up confusing things

### 0.6.2
Changes:
- removed entry name from data file name

Fixes:
- new function with new datafile in some cases threw an error, now fixed

### 0.6.1
Changes:
- Deprecated additional data from fits removed

## 0.6.0
Changes:
- strongly improved the NeXus entry
- added functionality to create a new file after a given number of hours (file includes same metadata)

### 0.5.1
Changes:
- improved the NeXus entry

## 0.5
Changes:
- Behavior of file-handling changed, now hdf5 file is being closed when events are separated by more than one second, this is to prevent loss of data if the program crashes while the file is still open (Note: this needs to be further improved, as the behavior only starts once the event has taken longer, i.e. if there are a few measurements that are fast and then it takes several seconds for the next one, in the mean time the file is still open and closes only after that measurement)

### 0.4.7

Changes:

- Now uses the dynamic file extensions coming from CAMELS (either `.h5` or `.nxs`) to save the data. Works with NOMAD CAMELS >= 1.8.0

### 0.4.6

Changes:

- variable signals now return dictionaries and not namedtuples (for NOMAD CAMELS starting with version 1.8.0). CAMELS suitcase can now handle these changes.

### 0.4.5
Fixes:
- events with more than one reading can now also be processed (e.g. for flyers)

### 0.4.4
Fixes:
- strings could only be saved once, now fixed

### 0.4.3
Changes:
- "experiment" renamed to "measurement"

Fixes:
- session name does not appear twice in filename anymore

## 0.4.2 Major metadata overhaul
Changes:
- The entry / file name is now only numbered, the timestamp was removed
- Split up sensors and outputs
- moved a lot of metadata into groups to make it easier to understand
- The sorting of what goes in the fabrication inside one instrument was changed
- moved start and end time into exp-description
- renamed time_since_start to ElapsedTime to be consistent with wording in CAMELS
- time is now a float timestamp, not anymore in ISO format
- supporting optional NeXus output

### 0.3.1
Improved the NOMAD identifier for samples, user and instruments

## 0.3.0
Refactored the way metadata of instruments is saved.

### 0.2.2
Bug that would create datasets at the instruments with too high length fixed.

### 0.2.1
Fixed bug with fits

## 0.2.0
Features:
- Added virtual datasets of measured data in instruments, resembling the NeXus standard more closely.
- More metadata for measured channels.

Fixes:
- Now correctly saving the variable signal also after run.


### 0.1.4
Fixed saving of string data.

### 0.1.3
Fixes:
- Fixed issue with empty data, this is now caught.
- can now save named tuples as they come from ophyd devices or camel's variable signal

### 0.1.2
Fixed issue with dots in paths

### 0.1.1
Added CAMELS plots to export function

## 0.1.0
Initial release
