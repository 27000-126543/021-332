#!/usr/bin/env python3
"""
竣工资料组卷批处理命令行工具
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from juanzuan.__main__ import main

if __name__ == "__main__":
    main()
