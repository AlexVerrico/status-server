# Copyright (C) 2021 Alex Verrico (https://alexverrico.com/) all rights reserved.
# For licensing enquiries please contact Alex Verrico (https://alexverrico.com/)

# #####################
# ### BEGIN IMPORTS ###
# #####################

from flask import Flask, request, jsonify, json
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
import confChecker

# ###################
# ### END IMPORTS ###
# ###################


# #############################
# ### BEGIN LOADING OF CONF ###
# #############################

# Create confChecker object
confChecker = confChecker.ConfChecker()

# List of critical environment variables
required_env_variables = ['CONF_FILE']

# Load the .env file
load_dotenv()

# Check whether critical environment variables are set
confChecker.check_env(required_env_variables)

# Get the location of the conf.yaml file
conf_file = os.getenv('CONF_FILE')
with open(conf_file, 'r') as f:
    conf = yaml.load(f, Loader=yaml.FullLoader)

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
                    # Delete the operation variable to avoid any chance of a memory leak
                    del operation
                    # Jump back to the start of the loop
                    continue
            elif operation[0] == 'new_row':
                with closing(sqlite3.connect(database_path)) as _con, closing(_con.cursor()) as cursor:
                    db_update_cmd = 'INSERT INTO %s VALUES (%s)'
                    param_list = []
                    for i in range(0, len(operation[2])):
                        param_list.append('?')
                    param_str = ','.join(param_list)
                    cursor.execute(db_update_cmd % (operation[1], param_str), operation[2])
                    _con.commit()
                    del operation
                    continue
            elif operation[0] == 'update_system_value':
                with closing(sqlite3.connect(database_path)) as _con, closing(_con.cursor()) as cursor:
                    db_fetch_value_cmd = 'SELECT system_data FROM systems_stats WHERE id = ?'
                    old_values = cursor.execute(db_fetch_value_cmd, (operation[1],)).fetchone()[0]
                    new_values = json.loads(old_values)
                    new_values[operation[2]] = json.loads(operation[3])
                    db_update_value_cmd = 'UPDATE systems_stats SET system_data = ? WHERE id = ?'
                    cursor.execute(db_update_value_cmd, (json.dumps(new_values), operation[1],))
                    _con.commit()
                    del operation
                    continue
            else:
                sleep(0.1)
                continue
        else:
            sleep(0.1)
            continue


def hash_password(password):
    # Hash a password for storing
    salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
    pwdhash = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000)
    pwdhash = binascii.hexlify(pwdhash)
    return (salt + pwdhash).decode('ascii')


def verify_password(stored_password, provided_password):
    # Verify a stored password against one provided by user
    salt = stored_password[:64]
    stored_password = stored_password[64:]
    pwdhash = hashlib.pbkdf2_hmac('sha512',
                                  provided_password.encode('utf-8'),
                                  salt.encode('ascii'),
                                  100000)
    pwdhash = binascii.hexlify(pwdhash).decode('ascii')
    return pwdhash == stored_password


# Check if a set of credentials is valid
def auth(_id, _auth, access_level='system'):
    # Create a database connection and cursor object
    with closing(sqlite3.connect(database_path)) as db_connection, closing(db_connection.cursor()) as db_cursor:
        _auth_cmd = 'SELECT password FROM auth WHERE id = ? AND access_level = ?'
        if access_level == 'system':
            _temp = db_cursor.execute(_auth_cmd, (str(_id), 'system',)).fetchone()
        elif access_level == 'client':
            _temp = db_cursor.execute(_auth_cmd, (str(_id), 'client',)).fetchone()
        elif access_level == 'admin':
            _temp = db_cursor.execute(_auth_cmd, (str(_id), 'admin',)).fetchone()
        elif access_level == 'owner':
            _temp = db_cursor.execute(_auth_cmd, (str(_id), 'owner',)).fetchone()
        elif access_level == 'any':
            _temp = db_cursor.execute('SELECT password FROM auth WHERE id = ?', (str(_id),)).fetchone()
        else:
            return False
        try:
            return verify_password(str(_temp[0]), str(_auth))
        except TypeError:
            return False


def generate_new_auth():
    char_blacklist = 'iI1lo0OBgzsS'
    temp = f'{ascii_lowercase}{ascii_digits}'
    id_rand_list = ''
    for i in temp:
        if i not in char_blacklist:
            id_rand_list = id_rand_list + i
    while True:
        id_out = ''
        for i in range(0, 6):
            id_out = f'{id_out}{choice(id_rand_list)}'
        with closing(sqlite3.connect(database_path)) as _db, closing(_db.cursor()) as _cur:
            if (id_out,) in _cur.execute('SELECT "id" FROM auth').fetchall():
                sleep(3)
                continue
            break
    temp = f'{temp}{ascii_uppercase}'
    pass_rand_list = ''
    for i in temp:
        if i not in char_blacklist:
            pass_rand_list = pass_rand_list + i
    pass_out = ''
    for i in range(0, 10):
        pass_out = f'{pass_out}{choice(pass_rand_list)}'
    hashed_pass_out = hash_password(pass_out)
    return id_out, pass_out, hashed_pass_out


def api_historical(_id, _val_name, _data):
    if api_enable_historical is True:
        with open(f'{historical_directory}{_id}/{_val_name}.txt', 'a') as f:
            f.write(f'"{time()}": "{str(_data)}"\n')
    return True

# #############################
# ### END GENERAL FUNCTIONS ###
# #############################


# #############################
# ### BEGIN ADMIN ENDPOINTS ###
# #############################

@app.route(f'{api_base_url}{api_admin_prefix}new_auth', methods=['POST', 'GET'])
def api_admin_new_auth():
    _system_name = None
    required_args = ['id', 'auth', 'access_level']
    for arg in required_args:
        if arg not in request.values:
            return f'Error: missing required argument "{arg}"', 400
    if request.args['access_level'] == 'system':
        if 'system_name' not in request.args:
            return 'Error: missing required argument "system_name"', 400
        _system_name = request.args['system_name']
    _id = request.args['id']
    _auth = request.args['auth']
    _access_level = request.args['access_level']
    if _access_level == 'admin':
        if auth(_id, _auth, access_level='owner') is False:
            return 'Error: you do not have the proper credentials', 401
    else:
        if auth(_id, _auth, access_level='admin') is False and auth(_id, _auth, access_level='owner') is False:
            return 'Error: you do not have the proper credentials', 401
    new_id, new_auth, hashed_new_auth = generate_new_auth()
    database_operations_queue.put(['new_row', 'auth', (new_id, hashed_new_auth, _access_level,)])
    if _system_name:
        database_operations_queue.put(['new_row', 'systems_stats', (new_id, _system_name, None, '{}')])
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
        if 'id' not in request.args:
            return 'Error: Missing required argument "id"', 400
        _id = request.args['id']
    if not _auth:
        if 'auth' not in request.args:
            return 'Error: Missing required argument "auth"', 400
        _auth = request.args['auth']
    if auth(_id, _auth, access_level='any') is False:
        return 'Error: you do not have the proper credentials', 401
    return '', 200

# #############################
# ### END GENERAL ENDPOINTS ###
# #############################


# ##############################
# ### BEGIN SYSTEM ENDPOINTS ###
# ##############################

@app.route(f'{api_base_url}{api_value_update_prefix}heartbeat', methods=['GET', 'POST'])
def api_update_heartbeat():
    required_args = ['id', 'auth']
    for arg in required_args:
        if arg not in request.values:
            return f'Error: missing required argument "{arg}"', 400
    _id = request.args['id']
    _auth = request.args['auth']
    if auth(_id, _auth, access_level='system') is False:
        return 'Error: you do not have the proper credentials', 401
    now = time()
    database_operations_queue.put(['update_row', 'systems_stats', str(_id), 'heartbeat', str(now)])
    api_historical(_id, 'heartbeat', now)
    return '', 200


@app.route(f'{api_base_url}{api_value_update_prefix}logging', methods=['GET', 'POST'])
def api_update_logging():
    required_args = ['id', 'auth', 'data']
    for arg in required_args:
        if arg not in request.values:
            return f'Error: missing required argument "{arg}"', 400
    _id = request.values['id']
    _auth = request.values['auth']
    if auth(_id, _auth, access_level='system') is False:
        return 'Error: you do not have the proper credentials', 401
    _data = request.values['data']
    with open(f"{log_directory}{str(_id)}.txt", 'a') as f:
        f.write(f'{time()}:     {str(_data)}\n\n\n')
    return '', 200


@app.route(f'{api_base_url}{api_value_update_prefix}main', methods=['GET', 'POST'])
def api_update_main():
    required_args = ['id', 'auth', 'value', 'data']
    for arg in required_args:
        if arg not in request.values:
            return f'Error: missing required argument "{arg}"', 400
    _id = request.values['id']
    _auth = request.values['auth']
    if auth(_id, _auth, access_level='system') is False:
        return 'Error: you do not have the proper credentials', 401
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
def api_fetch_main():
    required_args = ['id', 'auth', 'system_id', 'value']
    for arg in required_args:
        if arg not in request.values:
            return f'Error: missing required argument "{arg}"', 400
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
        _temp = json.loads(_cur.execute('SELECT system_data FROM systems_stats WHERE id = ?', (_system_id,)).fetchone()[0])
    try:
        return jsonify(_temp[_value])
    except KeyError:
        return 'Error: that value name does not exist yet for that system', 400


@app.route(f'{api_base_url}{api_value_fetch_prefix}heartbeat', methods=['GET', 'POST'])
def api_fetch_heartbeat():
    required_args = ['id', 'auth', 'system_id']
    for arg in required_args:
        if arg not in request.values:
            return f'Error: missing required argument "{arg}"', 400
    _id = request.values['id']
    _auth = request.values['auth']
    if auth(_id, _auth, access_level='client') is False and \
            auth(_id, _auth, access_level='admin') is False and \
            auth(_id, _auth, access_level='owner') is False:
        return 'Error: you do not have the proper credentials', 401
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
