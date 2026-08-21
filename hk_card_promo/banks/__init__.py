# -*- coding: utf-8 -*-
"""银行适配器注册表：新增银行时在 banks/ 下实现同名模块即可"""
from banks import bea, icbcasia

ADAPTERS = {
    "bea": bea,
    "icbcasia": icbcasia,
}
