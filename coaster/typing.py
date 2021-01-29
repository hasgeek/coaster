"""
Coaster types
-------------
"""
from typing import Callable

#: Type for a simple function decorator that does not accept options
SimpleDecorator = Callable[[Callable], Callable]
