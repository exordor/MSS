The current transformers (in terms of signal connection) are currently wired as follows:
1) Current transformer for measurement technology (Messtechnik)
Based on the power data you provided for all sensors, I estimate that the 24V battery needs to supply a maximum current of approximately 10A.
This current transformer itself can measure up to 100A. If I pass the cable through the transformer multiple times, smaller currents can be measured more accurately because the magnetic field generated will be stronger.
Since only 10A is expected here, I passed the cable through the transformer 8 times. This way, the maximum measurable current becomes 12.5A.
This 12.5A upper limit is important for your data analysis/evaluation.
When the current is 12.5A, the analog input of the A/D converter will be 3V. (When 0A = 0V)
2) Current transformer for the drive (Antrieb)
Here, the maximum current is expected to be approximately 2 × 17A = 34A.
The cable here is passed through the transformer 3 times. This results in a maximum measurable current of 33.33A.
Although this is slightly lower than the maximum current shown in the thruster (Thruster) datasheet, we will try it this way for now.
When the current is 33.33A, another analog input of the A/D converter will be 3V.
3) A/D converter and Jetson
The A/D converter (ADS1115) will digitize these two analog values and then send them to the Jetson via I²C at address 0x48.
However, you still need to configure/set up this A/D converter accordingly.
You can search for ADS1115 on AZ-Delivery, where you will find relevant information.
4) One last thing
For the wire connected to the Jetson, I still need to attach a plug/connector that fits the GPIO pins.