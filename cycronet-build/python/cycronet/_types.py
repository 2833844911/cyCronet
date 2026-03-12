"""
Type definitions and constants for cycronet.
"""

from typing import Union, Dict, List, Tuple, Any


# Type aliases
HeadersType = Union[Dict[str, str], List[Tuple[str, str]]]
CookiesType = Dict[str, str]
DataType = Union[str, bytes, Dict[str, Any], None]
