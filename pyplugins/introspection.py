import os
import subprocess
import threading
import queue
from collections import Counter
import math
import time
from penguin import plugins, Plugin
import itertools
import string
import yaml

class Instrospection(Plugin):
    def __init__(self):
        self.text = "hello world"
        print("My plugin is initialized!!!")

    def dostuff(self):
        print("hello world")

    def uninit(self):
        print("HELLOOOO WORLDDD HEHEHE")



