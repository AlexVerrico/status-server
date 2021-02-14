# Status Server

A lightweight centralised logging and status monitor server  
This component is just the server-side logic to store all the data and provide a method to access it.  
The next step is to develop a client app/webpage which can connect to this API to display the data in a user-friendly way

## Setup
Download and extract the latest release  
move `sample.env` to `.env` and change the values inside it to suit your environment  
move `sample.sqlite` to `main.sqlite` and change the owner password (generate a new password using the file `hashPassword.py`)  
move `sample_conf.yaml` to `conf.yaml` and change the values inside it to suit your environment  
install the python requirements (`pip install -r requirements.txt`)  
run the program (`python main.py`)
