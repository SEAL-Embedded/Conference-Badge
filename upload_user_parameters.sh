# This file must be run on Bash, and it uploads a json file with given user inputs to the ESP32. Please note that you must cd into the 
# directory where this is saved, then just run this in the terminal: ./upload_user_parameters.sh
# It asks the user for several parameters, then uploads them onto the ESP32. 

#!/bin/bash

clear

echo "MicroPython Provisioning Tool"
echo

PORT=$1

if [[ -z "$PORT" ]]; then
    PORT=$(ls /dev/ttyUSB* /dev/tty.usbserial* /dev/cu.usbserial* 2>/dev/null | head -n 1)
    echo "Using $PORT as default port."
else
    echo "Using port $PORT."
fi
echo

# --- SAFETY CHECK ---
if [[ -z "$PORT" ]]; then
  echo "No ESP32 detected."
  exit 1
fi

# --- USER INPUT ---
echo "Research field:"
read RESEARCH_FIELD

echo "Home institution:"
read HOME_INSTITUTION

echo "Company affiliation:"
read COMPANY_AFFILIATION

# --- OPTIONAL: AUTO DEVICE ID ---
DEVICE_ID=$(date +%s)

mkdir -p ./data_upload
# --- CREATE CONFIG FILE ---
printf '{
  "device_id": "%s",
  "research_field": "%s",
  "home_institution": "%s",
  "company_affiliation": "%s"
}\n' \
"$DEVICE_ID" \
"$RESEARCH_FIELD" \
"$HOME_INSTITUTION" \
"$COMPANY_AFFILIATION" > ./data_upload/config.json

echo
echo "Uploading config to ESP32..."

# --- UPLOAD USING mpremote ---
python3 -m mpremote connect "$PORT" fs cp ./data_upload/config.json :/config.json

# --- OPTIONAL: UPLOAD main.py IF NEEDED ---
# mpremote connect "$PORT" fs cp ./main.py :/main.py

echo "Provisioning complete!"
echo "Device ID: $DEVICE_ID"
