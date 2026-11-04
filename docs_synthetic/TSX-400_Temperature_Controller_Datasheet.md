# TSX-400 Temperature Controller Datasheet (rev 4, 2025-11)

## 1 Overview
The TSX-400 is a PID temperature controller for industrial furnaces and plastic
processing equipment. It accepts one K/J/PT100 input and drives a 4-20 mA output
plus two relay stages 8 A resistive.

## 2 Electrical specifications
Supply voltage: 24 VDC, tolerance +/-10 percent (21.6 to 26.4 VDC).
Power consumption: 4.5 W maximum. Relay output rating: 8 A at 250 VAC resistive load.
Analog output: 4-20 mA, maximum loop resistance 600 ohm.

## 3 Operating ranges
Measurement input range: -20 to 150 degC for PT100, -50 to 400 degC for type K.
Setpoint range: 0 to 120 degC with a span limit of 40 degC between heat and cool
setpoints. Overshoot protection trips the relay when the process value exceeds the
setpoint by 15 degC for more than 30 seconds.

## 4 Calibration
Accuracy: +/-0.1 percent of full scale after calibration. A single-turn offset
trimmer on the front panel trims zero drift; full recalibration requires the TSC-2
calibrator connected to the rear service jack. Calibration interval is 24 months.

## 5 Fault codes
F01: sensor break. F02: reverse polarity. F03: output short circuit. F04: EEPROM
checksum failure (return to factory). Fault latch: press ENTER for 5 s to clear
F01-F03 after the cause is fixed.
