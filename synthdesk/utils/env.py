"""
env utils for runtime, paths, configs.
"""

import os


def project_root():
    return os.path.dirname(os.path.dirname(__file__))

