import hashlib
import binascii
import os
import yaml
import sqlite3
from random import choice
from string import ascii_lowercase, digits as ascii_digits, ascii_uppercase
from json import dumps as json_dumps


def hash_password(password):
    """Hash a password for storing."""
    salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
    pwdhash = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000)
    pwdhash = binascii.hexlify(pwdhash)
    return (salt + pwdhash).decode('ascii')


def generate_new_auth():
    char_blacklist = 'iI1lo0OBgzsS'  # Don't use certain characters for IDs and passwords to avoid ambiguity
    temp = f'{ascii_lowercase}{ascii_digits}'
    id_rand_list = ''
    for i in temp:
        if i not in char_blacklist:
            id_rand_list = id_rand_list + i
    id_out = ''
    for i in range(0, 6):
        id_out = f'{id_out}{choice(id_rand_list)}'
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


if __name__ == '__main__':
    print('Status server initial setup wizard')
    print('Copyright (C) 2021 Alex Verrico (https://alexverrico.com/)')
    base_path = os.getcwd().replace('\\', '/')
    print(f'We detected that the path to the main.py file is {base_path}/main.py. Is this correct? [y] [n]')
    base_correct = input()
    if base_correct == 'n':
        print('Please enter the path to the main.py file: ')
        base_path = input().replace('main.py', '').replace('\\', '/')
        if base_path[-1] == '/':
            base_path = base_path[0:-1]
    print(f'Base directory "{base_path}" will be used for the rest of the setup.')

    print('WARNING: The following files will be deleted before beginning setup if they exist:')
    print(f'{base_path}/conf.yaml')
    print(f'{base_path}/.env')
    print(f'{base_path}/main.sqlite')
    print('Do you want to continue? [y] [n]')
    if input() != 'y':
        print("Exiting, please run the program again once you have backed up these files")

    if os.path.isfile(f'{base_path}/conf.yaml') is True:
        os.remove(f'{base_path}/conf.yaml')

    if os.path.isfile(f'{base_path}/.env') is True:
        os.remove(f'{base_path}/.env')

    if os.path.isfile(f'{base_path}/main.sqlite') is True:
        os.remove(f'{base_path}/main.sqlite')

    # Create .env file
    with open(f'{base_path}/.env', 'w') as f:
        f.write(f'CONF_FILE={base_path}/conf.yaml\n')

    # Create conf.yaml
    conf_yaml = {
        'main_conf': {
            'api_config': {
                'value_update_prefix': 'update/',
                'value_fetch_prefix': 'fetch/',
                'admin_prefix': 'admin/',
                'general_prefix': 'general/'
            },
            'environment_config': {
                'base_directory': f'{base_path}/',
                'database_name': 'main.sqlite',
                'log_directory': 'logs/'
            }
        }
    }
    api_conf = conf_yaml['main_conf']['api_config']
    env_conf = conf_yaml['main_conf']['environment_config']

    print('What will the base URL of the API be (eg. if you access the API at http://example.com/api/v1/, then the base URL is /api/v1/):')
    while True:
        api_conf['api_base_url'] = input()
        if api_conf['api_base_url'][0] == '/' and api_conf['api_base_url'][-1] == '/':
            break
        print('Error, invalid input, please try again:')

    print('Enable flask debug mode? [y] [n]')
    if input() == 'y':
        api_conf['flask_debug'] = True
    else:
        api_conf['flask_debug'] = False

    print('What TCP port should the software bind to?')
    while True:
        try:
            api_conf['flask_port'] = int(input())
        except ValueError:
            print("Error: input is not a valid integer, please try again:")
            continue
        if int(api_conf['flask_port']) > 65536 or int(api_conf['flask_port']) < 0:
            print("Error: input is not a valid port number, please try again:")
        break

    print('What address should the software bind to (eg. localhost, 10.0.0.1, 0.0.0.0, etc)?')
    api_conf['flask_address'] = input()

    print('Do you want to enable historical logging of data (See docs for details)? [y] [n]')
    if input() == 'y':
        api_conf['enable_historical'] = True
    else:
        api_conf['enable_historical'] = False

    with open(f'{base_path}/conf.yaml', 'w') as f:
        yaml.dump(conf_yaml, f)

    with open(f'{base_path}/conf.yaml', 'r') as f:
        temp = f.read()\
            .replace(' true', ' True')\
            .replace(' false', ' False')\
            .replace(':false', ':False')\
            .replace(':true', ':True')

    with open(f'{base_path}/conf.yaml', 'w') as f:
        f.write(temp)
        del temp

    if os.path.isfile(f'{base_path}/main.sqlite') is True:
        os.remove(f'{base_path}/main.sqlite')
    con = sqlite3.connect(f'{base_path}/main.sqlite')
    cur = con.cursor()
    cur.execute('CREATE TABLE "auth" ("id" TEXT,"password" TEXT,"access_level" TEXT,PRIMARY KEY("id"))')
    cur.execute('CREATE TABLE "systems_stats" ("id" TEXT,"system_name" TEXT,"heartbeat" TEXT,"system_data" TEXT,PRIMARY KEY("id"))')
    con.commit()
    owner_id, owner_pass, owner_hashed_pass = generate_new_auth()
    cur.execute('INSERT INTO auth VALUES(?, ?, "owner")', (owner_id, owner_hashed_pass,))
    con.commit()
    con.close()
    print(f'"Owner" level credentials: ')
    print(json_dumps({'id': owner_id, 'auth': owner_pass}))
    exit(0)
