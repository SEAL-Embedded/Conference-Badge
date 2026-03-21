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

# tells you if nothing is detected
if [[ -z "$PORT" ]]; then
  echo "No ESP32 detected."
  exit 1
fi

# Get user input
echo "Research field:"
read RESEARCH_FIELD

echo "Home institution:"
read HOME_INSTITUTION

echo "Company affiliation:"
read COMPANY_AFFILIATION

# gets the device ID, which is unique to every ESP32
DEVICE_ID=$(date +%s)

mkdir -p ./data_upload
# create the configuration file
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

# upload the file
python3 -m mpremote connect "$PORT" fs cp ./data_upload/config.json :/config.json


# mpremote connect "$PORT" fs cp ./main.py :/main.py

echo "Provisioning complete"
echo "Device ID: $DEVICE_ID"

# After creating this file, you can have it run on startup by doing something like the following:
# Note that this will need some tweaking for the specific directories and stuff

# chmod +x get_user_parameters.sh
#./get_user_parameters.sh

#sudo nano /etc/systemd/system/get_user_parameters.service

#[Unit]
#Description=Get User Parameters
#After=network.target

#[Service]
#User=IDK PUT SOMETHING HERE DEPENDS ON THE DEVICE
#WorkingDirectory=/WHEREVER YOUR DIRECTORY IS
#ExecStart=/YOUR BASH FILE DIRECTORY/get_user_parameters.sh
#Restart=always

#[Install]
#WantedBy=multi-user.target

#sudo systemctl daemon-reload
#sudo systemctl enable get_user_parameters
#sudo systemctl start get_user_parameters

#There's a way to stop it on every startup with some sudo systemctl command but I don't remember at the moment
