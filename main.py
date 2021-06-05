# Copyright (C) 2021 Alex Verrico (https://alexverrico.com/) All Rights Reserved.
# For licensing enquiries please contact Alex Verrico (https://alexverrico.com/)

# #####################
# ### BEGIN IMPORTS ###
# #####################
from flask import Flask, request, jsonify, json, abort
import sqlite3
from dotenv import load_dotenv
import os
from queue import Queue
from threading import Timer
from time import sleep, time
from random import choice
from string import ascii_lowercase, digits as ascii_digits, ascii_uppercase
import yaml
from contextlib import closing
import hashlib
import binascii
import python_confChecker as confChecker
from functools import wraps

# ###################
# ### END IMPORTS ###
# ###################


# #############################
# ### BEGIN LOADING OF CONF ###
# #############################

# List of critical environment variables
required_env_variables = ['CONF_FILE']

# Load the .env file
load_dotenv()

# Check whether critical environment variables are set
confChecker.check_env(required_env_variables)

# Get the location of the conf.yaml file
conf_file = os.getenv('CONF_FILE')
# Load the conf.yaml file and store it as conf
with open(conf_file, 'r') as f:
    conf = yaml.safe_load(f)

# List of critical conf.yaml values
required_conf_variables = [['main_conf', 'environment_config', 'base_directory'],
                           ['main_conf', 'environment_config', 'database_name'],
                           ['main_conf', 'environment_config', 'log_directory'],
                           ['main_conf', 'api_config', 'api_base_url'],
                           ['main_conf', 'api_config', 'flask_debug'],
                           ['main_conf', 'api_config', 'flask_port'],
                           ['main_conf', 'api_config', 'flask_address'],
                           ['main_conf', 'api_config', 'value_update_prefix'],
                           ['main_conf', 'api_config', 'enable_historical'],
                           ['main_conf', 'api_config', 'admin_prefix'],
                           ['main_conf', 'api_config', 'general_prefix'],
                           ['main_conf', 'api_config', 'value_fetch_prefix']]

# Check whether critical conf.yaml values are set
confChecker.check_yaml(conf, required_conf_variables)

# Declare globally used variables
environment_config = conf['main_conf']['environment_config']
api_config = conf['main_conf']['api_config']

api_base_url = api_config['api_base_url']
api_value_update_prefix = api_config['value_update_prefix']
api_value_fetch_prefix = api_config['value_fetch_prefix']
api_admin_prefix = api_config['admin_prefix']
api_general_prefix = api_config['general_prefix']
api_enable_historical = api_config['enable_historical']

base_directory = environment_config['base_directory']
database_path = f"{base_directory}{environment_config['database_name']}"
log_directory = f"{base_directory}{environment_config['log_directory']}"
historical_directory = f"{base_directory}historical/"

# Create the flask object
app = Flask(__name__)
# Enable debugging if specified in the conf.yaml file
app.config['DEBUG'] = api_config['flask_debug']

# ###########################
# ### END LOADING OF CONF ###
# ###########################


# ###############################
# ### BEGIN GENERAL FUNCTIONS ###
# ###############################

# Create a custom logging function
def system_log(data):
    # Open the file SYSTEM.txt in the configured log directory in append mode
    with open(f"{log_directory}SYSTEM.txt", 'a') as log_file:
        # Append the provided data to the file
        log_file.write(f'{time()}: {str(data)}\n\n\n')
    return


# Create a function that will run asynchronously to write to the database
def run_queue():
    # Start a loop that will run until killed
    while True:
        # If a job exists in the queue
        if database_operations_queue.empty() is False:
            # Fetch the job from the queue (also removes it from the queue to avoid executing it multiple times)
            operation = database_operations_queue.get()
            # Check if the job type is update_row
            if operation[0] == 'update_row':
                # Create a connection the database which will automatically close
                with closing(sqlite3.connect(database_path)) as _con, closing(_con.cursor()) as cursor:
                    # Define the SQL command to run
                    db_update_cmd = 'UPDATE %s SET %s = ? WHERE id = ?'
                    # Run the SQL command
                    cursor.execute(db_update_cmd % (operation[1], operation[3]), (operation[4], operation[2],))
                    # Commit the changes
                    _con.commit()
                    # Delete the variables that we are finished with to avoid any chance of a memory leak
                    del operation
                    del db_update_cmd
                    # Jump back to the start of the loop
                    continue
            # Check if the job type is new_row
            elif operation[0] == 'new_row':
                # Create a connection the database which will automatically close
                with closing(sqlite3.connect(database_path)) as _con, closing(_con.cursor()) as cursor:
                    # Define the SQL command to run
                    db_update_cmd = 'INSERT INTO %s VALUES (%s)'
                    # Creat the tuple of values to insert into the new row
                    param_list = []
                    for i in range(0, len(operation[2])):
                        param_list.append('?')
                    param_str = ','.join(param_list)
                    # Run the SQL command
                    cursor.execute(db_update_cmd % (operation[1], param_str), operation[2])
                    # Commit the changes
                    _con.commit()
                    # Delete the variables that we are finished with to avoid any chance of a memory leak
                    del operation
                    del db_update_cmd
                    del param_list
                    del param_str
                    # Jump back to the start of the loop
                    continue
            # Check if the job type is update_system_value
            elif operation[0] == 'update_system_value':
                # Create a connection the database which will automatically close
                with closing(sqlite3.connect(database_path)) as _con, closing(_con.cursor()) as cursor:
                    # Define the SQL command to run to get the current system value(s)
                    db_fetch_value_cmd = 'SELECT system_data FROM systems_stats WHERE id = ?'
                    # Fetch the current value(s) from the database
                    old_values = cursor.execute(db_fetch_value_cmd, (operation[1],)).fetchone()[0]
                    # Load the current values as a json object to make manipulation easier
                    new_values = json.loads(old_values)
                    # Store the new value
                    new_values[operation[2]] = json.loads(operation[3])
                    # Define the SQL command to store the new value
                    db_update_value_cmd = 'UPDATE systems_stats SET system_data = ? WHERE id = ?'
                    # Run the SQL command to store the new values
                    cursor.execute(db_update_value_cmd, (json.dumps(new_values), operation[1],))
                    # Commit the changes
                    _con.commit()
                    # Delete the variables that we are finished with to avoid any chance of a memory leak
                    del operation
                    del db_fetch_value_cmd
                    del db_update_value_cmd
                    del old_values
                    del new_values
                    # Jump back to the start of the loop
                    continue
            else:
                # Log the unsupported operation
                system_log(f'ERROR:000001 Unrecognised operation in DB queue: {operation}\n')
                # Wait 0.1 seconds then skip back to the start of the loop
                sleep(0.1)
                continue
        else:
            # Wait 0.1 seconds then skip back to the start of the loop
            sleep(0.1)
            continue


# Create a function to hash a password
def hash_password(password):
    # Generate some salt to add to the password
    salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
    # Hash the password along with the salt
    pw_hash = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000)
    # Convert the binary hash to hexadecimal
    pw_hash = binascii.hexlify(pw_hash)
    # Return the hashed password
    return (salt + pw_hash).decode('ascii')


# Create a function to compare a plaintext password to a hashed password
def verify_password(stored_password, provided_password):
    # Get the salt from the stored password
    salt = stored_password[:64]
    # Get the hash of the stored password
    stored_password = stored_password[64:]
    # Generate a hash for the provided_password
    pw_hash = hashlib.pbkdf2_hmac('sha512',
                                  provided_password.encode('utf-8'),
                                  salt.encode('ascii'),
                                  100000)
    # Convert the binary hash to hexadecimal
    pw_hash = binascii.hexlify(pw_hash).decode('ascii')
    # Compare the provided passwords
    return pw_hash == stored_password


# Create a function to check if a set of credentials is valid
def auth(_id, _auth, access_level='system'):
    # Create a database connection and cursor object
    with closing(sqlite3.connect(database_path)) as db_connection, closing(db_connection.cursor()) as db_cursor:
        # define the command for fetching the password
        _auth_cmd = 'SELECT password FROM auth WHERE id = ? AND access_level = ?'
        # Check what access level the client is attempting to authenticate for and execute the appropriate command
        if access_level == 'system':
            _temp = db_cursor.execute(_auth_cmd, (str(_id), 'system',)).fetchone()
        elif access_level == 'client':
            _temp = db_cursor.execute(_auth_cmd, (str(_id), 'client',)).fetchone()
        elif access_level == 'admin':
            _temp = db_cursor.execute(_auth_cmd, (str(_id), 'admin',)).fetchone()
        elif access_level == 'owner':
            _temp = db_cursor.execute(_auth_cmd, (str(_id), 'owner',)).fetchone()
        # This allows a client to check if they are in the database anywhere regardless of their access level
        elif access_level == 'any':
            _temp = db_cursor.execute('SELECT password FROM auth WHERE id = ?', (str(_id),)).fetchone()
        # If the access level provided was unrecognised we log it and return False
        else:
            system_log(f'ERROR:000002 Unrecognised access_level in auth(): {access_level}\n')
            return False
        # Attempt to convert the stored password and provided password to
        # strings then return the result of verify_password()
        try:
            return verify_password(str(_temp[0]), str(_auth))
        # If converting the stored password and provided passwords to strings fails then log it and return False
        except TypeError:
            system_log(f'WARN: Failed to convert passwords to strings')
            return False
        return False


# Create a function to generate a new set of credentials for the API
def generate_new_auth():
    # Don't use certain characters for IDs and passwords to avoid ambiguity
    char_blacklist = 'iI1lo0OBgzsS'
    # Create the list of characters to use for ID generation
    id_rand_list = ''
    for i in f'{ascii_lowercase}{ascii_digits}':
        if i not in char_blacklist:
            id_rand_list = id_rand_list + i
    # Start a loop to continue generating IDs until we generate an unused one
    while True:
        # Generate an ID
        id_out = ''
        for i in range(0, 6):
            id_out = f'{id_out}{choice(id_rand_list)}'
        # Check if the ID is already in use
        with closing(sqlite3.connect(database_path)) as _db, closing(_db.cursor()) as _cur:
            if (id_out,) in _cur.execute('SELECT "id" FROM auth').fetchall():
                sleep(3)
                continue
            # If the ID isn't used then we break out of this loop
            break
    # Create the list of characters to use for password generation
    pass_rand_list = ''
    for i in f'{ascii_lowercase}{ascii_digits}{ascii_uppercase}':
        if i not in char_blacklist:
            pass_rand_list = pass_rand_list + i
    # Generate a password
    pass_out = ''
    for i in range(0, 10):
        pass_out = f'{pass_out}{choice(pass_rand_list)}'
    # Hash the generate password
    hashed_pass_out = hash_password(pass_out)
    # Return the generated password in plaintext and hashed form, along with the ID
    return id_out, pass_out, hashed_pass_out


# Create a function for logging historical API data for later analysis
def api_historical(_id, _val_name, _data):
    # Check if we should be logging historical data
    if api_enable_historical is True:
        # Open the file in append mode
        with open(f'{historical_directory}{_id}/{_val_name}.txt', 'a') as historical_file:
            # Append the value
            historical_file.write(f'"{time()}": "{str(_data)}"\n')
    return True


# Create a decorator function to use for checking if a user of the api is authorised
def check_auth(access_level):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if type(access_level) == str:
                # If the argument access_level is a string,
                # check whether the provided id is authorised for a single access_level
                authorised = auth(request.values['id'], request.values['auth'], access_level=access_level)
                if authorised is False:
                    # Let the client know that their credentials were invalid
                    abort(401, description='Error: you do not have the proper credentials')
                else:
                    return function(*args, **kwargs)

            elif type(access_level) == list:
                # If the argument access_level is a list,
                # check where the provided id is authorised for any of the access_levels in the list
                authorised = []
                # Loop through the provided list of access_levels, checking
                # each one and appending the result to "authorised"
                for level in access_level:
                    authorised.append(auth(request.values['id'], request.values['auth'], access_level=level))
                if True in authorised:
                    return function(*args, **kwargs)
                else:
                    # Let the client know that their credentials were invalid
                    abort(401, description='Error: you do not have the proper credentials')
            else:
                # Log that the argument access_level is an unsupported type
                system_log(f'ERROR:000004 access_level type is {type(access_level)}')
        return wrapper
    return decorator


# Create a decorator function to use for checking whether all required arguments have been supplied to an api endpoint
def check_args(required_args):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            for arg in required_args:
                if arg not in request.values:
                    abort(400, description=f'Error: missing required argument "{arg}"')
            return function(*args, **kwargs)
        return wrapper
    return decorator

# #############################
# ### END GENERAL FUNCTIONS ###
# #############################


# #############################
# ### BEGIN ADMIN ENDPOINTS ###
# #############################

@app.route(f'{api_base_url}{api_admin_prefix}new_auth', methods=['POST', 'GET'])
@check_args(required_args=['id', 'auth', 'access_level'])
def api_admin_new_auth():
    _system_name = None
    _id = request.values['id']
    _auth = request.values['auth']
    _access_level = request.values['access_level']
    if _access_level == 'admin':
        if auth(_id, _auth, access_level='owner') is False:
            return 'Error: you do not have the proper credentials', 401
    else:
        if auth(_id, _auth, access_level='admin') is False and auth(_id, _auth, access_level='owner') is False:
            return 'Error: you do not have the proper credentials', 401
    new_id, new_auth, hashed_new_auth = generate_new_auth()
    database_operations_queue.put(['new_row', 'auth', (new_id, hashed_new_auth, _access_level,)])
    if _access_level == 'system':
        database_operations_queue.put(['new_row', 'systems_stats', (new_id, '', None, '{}')])
    if os.path.exists(f'{historical_directory}{new_id}/') is False:
        os.makedirs(f'{historical_directory}{new_id}/')
    sleep(5)
    trash, response = api_check_auth(_id=new_id, _auth=new_auth)
    if response == 200:
        return jsonify({'id': new_id, 'auth': new_auth}), 200
    return 'Error', 500

# ###########################
# ### END ADMIN ENDPOINTS ###
# ###########################


# ###############################
# ### BEGIN GENERAL ENDPOINTS ###
# ###############################

@app.route(f'{api_base_url}{api_general_prefix}check_auth', methods=['POST', 'GET'])
def api_check_auth(_id=None, _auth=None):
    if not _id:
        if 'id' not in request.values:
            return 'Error: Missing required argument "id"', 400
        _id = request.values['id']
    if not _auth:
        if 'auth' not in request.values:
            return 'Error: Missing required argument "auth"', 400
        _auth = request.values['auth']
    if auth(_id, _auth, access_level='any') is False:
        return 'Error: you do not have the proper credentials', 401
    return '', 200

# #############################
# ### END GENERAL ENDPOINTS ###
# #############################


# ##############################
# ### BEGIN SYSTEM ENDPOINTS ###
# ##############################

@app.route(f'{api_base_url}{api_value_update_prefix}heartbeat', methods=['POST', 'GET'])
@check_args(required_args=['id', 'auth'])
@check_auth(access_level='system')
def api_update_heartbeat():
    _id = request.values['id']
    now = time()
    database_operations_queue.put(['update_row', 'systems_stats', str(_id), 'heartbeat', str(now)])
    api_historical(_id, 'heartbeat', now)
    return '', 200


@app.route(f'{api_base_url}{api_value_update_prefix}logging', methods=['POST'])
@check_args(required_args=['id', 'auth', 'data'])
@check_auth(access_level='system')
def api_update_logging():
    _id = request.values['id']
    _data = request.values['data']
    with open(f"{log_directory}{str(_id)}.txt", 'a') as log_file:
        log_file.write(f'{time()}: {str(_data)}\n\n\n')
    return '', 200


@app.route(f'{api_base_url}{api_value_update_prefix}main', methods=['POST'])
@check_args(required_args=['id', 'auth', 'value', 'data'])
@check_auth(access_level='system')
def api_update_main():
    _id = request.values['id']
    _value = request.values['value']
    try:
        _data = json.loads(request.values['data'])
    except:
        return 'Error: invalid "data" value', 500
    database_operations_queue.put(['update_system_value', str(_id), str(_value), json.dumps(_data)])
    return '', 200


# ############################
# ### END SYSTEM ENDPOINTS ###
# ############################


# ##############################
# ### BEGIN CLIENT ENDPOINTS ###
# ##############################

@app.route(f'{api_base_url}{api_value_fetch_prefix}main', methods=['GET', 'POST'])
@check_args(required_args=['id', 'auth', 'system_id', 'value'])
@check_auth(access_level='client')
def api_fetch_main():
    _id = request.values['id']
    _auth = request.values['auth']
    if auth(_id, _auth, access_level='client') is False and \
            auth(_id, _auth, access_level='admin') is False and \
            auth(_id, _auth, access_level='owner') is False:
        return 'Error: you do not have the proper credentials', 401
    _value = request.values['value']
    _system_id = request.values['system_id']
    with closing(sqlite3.connect(database_path)) as _db, closing(_db.cursor()) as _cur:
        if (str(_system_id),) not in _cur.execute('SELECT id FROM auth').fetchall():
            return 'Error: that system ID does not exist', 400
    with closing(sqlite3.connect(database_path)) as _db, closing(_db.cursor()) as _cur:
        _temp = json.loads(_cur.execute(
            'SELECT system_data FROM systems_stats WHERE id = ?',
            (_system_id,)
        ).fetchone()[0])
    try:
        return jsonify(_temp[_value])
    except KeyError:
        return 'Error: that value name does not exist yet for that system', 400


@app.route(f'{api_base_url}{api_value_fetch_prefix}heartbeat', methods=['GET', 'POST'])
@check_args(required_args=['id', 'auth', 'system_id'])
@check_auth(access_level=['client', 'admin', 'owner'])
def api_fetch_heartbeat():
    _id = request.values['id']
    _system_id = request.values['system_id']
    with closing(sqlite3.connect(database_path)) as _db, closing(_db.cursor()) as _cur:
        if (str(_system_id),) not in _cur.execute('SELECT id FROM auth').fetchall():
            return 'Error: that system ID does not exist', 400
    with closing(sqlite3.connect(database_path)) as _db, closing(_db.cursor()) as _cur:
        _temp = _cur.execute('SELECT heartbeat FROM systems_stats WHERE id = ?', (_system_id,)).fetchone()[0]
    return _temp

# ############################
# ### END CLIENT ENDPOINTS ###
# ############################


# #############################
# ### BEGIN GENERAL STARTUP ###
# #############################

# Create a queue to store write operations for the database in
database_operations_queue = Queue(maxsize=0)

# Create a Timer object to enable the function run_queue() to run asynchronously to the main program
t = Timer(0, run_queue)

# Start the Timer object
t.start()

# If the script has being executed with no special arguments using "python main.py", start the Flask server
if __name__ == '__main__':
    app.run(api_config['flask_address'], api_config['flask_port'])

# ###########################
# ### END GENERAL STARTUP ###
# ###########################
