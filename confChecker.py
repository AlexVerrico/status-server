# Copyright (C) 2021 Alex Verrico (https://alexverrico.com/) All Rights Reserved.
# For licensing enquiries please contact Alex Verrico (https://alexverrico.com/)

# #####################
# ### BEGIN IMPORTS ###
# #####################

from typing import List
from dotenv import load_dotenv
import os

# ###################
# ### END IMPORTS ###
# ###################


class ConfChecker:
    def check_for_conf_key(self, level_list: List, current_level):
        try:
            x = current_level[level_list.pop(0)]
            if level_list:
                self.check_for_conf_key(level_list, x)
        except TypeError:
            raise KeyError

    # Check whether critical environment variables are set, and if not raise an exception
    def check_env(self, required_vars):
        load_dotenv()
        for i in required_vars:
            if os.getenv(i) is None:
                raise Exception(f'Fatal Error: Environment Variable {i} not defined')

    # Check whether critical conf.yaml values are set, and if not raise an exception
    def check_yaml(self, conf, required_vars):
        for var_list in required_vars:
            x = var_list[0:]
            try:
                self.check_for_conf_key(x, conf)
            except KeyError:
                raise Exception(f'Fatal Error: conf key \"{"->".join(var_list)}\" is non-existent')
            finally:
                del x
