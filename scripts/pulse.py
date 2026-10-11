'''
Created By: Romel
'''

import RPi.GPIO as GPIO # Import Raspberry Pi GPIO library
from time import sleep # Import the sleep function from the time module
GPIO.setwarnings(False) # Ignore warning for now
GPIO.setmode(GPIO.BCM) # Use physical pin numbering BOARD or GPIO BCM
GPIO.setup(17, GPIO.OUT, initial=GPIO.LOW) # Set pin 8 to be an output pin and set initial value to low (off)

try:
 while True: # Run forever
  GPIO.output(17, GPIO.HIGH) # Turn on
  sleep(7) # Sleep for 7 second
  GPIO.output(17, GPIO.LOW) # Turn off
  sleep(1) # Sleep for 1 second

except KeyboardInterrupt:  
 GPIO.cleanup()       # clean up GPIO on CTRL+C exit  
GPIO.cleanup()           # clean up GPIO on normal exit
