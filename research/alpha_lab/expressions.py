"""Restricted factor expressions; input text is parsed, never evaluated as code."""
from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

FIELDS = {"close", "volume"}
WINDOWS = {"delay", "ts_mean", "ts_std", "delta"}
UNARY = {"rank", "neg", "abs"}


def parse(expression):
    if not isinstance(expression, str) or len(expression) > 1000:
        raise ValueError("expression must be a string of at most 1000 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("invalid expression syntax") from exc
    if sum(1 for _ in ast.walk(tree)) > 150:
        raise ValueError("expression is too complex")

    def check(node, depth=0):
        if depth > 16:
            raise ValueError("expression nesting limit exceeded")
        if isinstance(node, ast.Name) and node.id in FIELDS:
            return node.id
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name in UNARY and len(node.args) == 1:
                return [name, check(node.args[0], depth + 1)]
            if name in WINDOWS and len(node.args) == 2:
                window = node.args[1]
                if not isinstance(window, ast.Constant) or type(window.value) is not int or not 1 <= window.value <= 252:
                    raise ValueError("window must be an integer from 1 to 252")
                return [name, check(node.args[0], depth + 1), window.value]
            if name in {"add", "sub", "mul", "div"} and len(node.args) == 2:
                return [name, check(node.args[0], depth + 1), check(node.args[1], depth + 1)]
        raise ValueError("unsupported field, operator, argument, or Python syntax")

    return check(tree.body)


def fingerprint(expression):
    return hashlib.sha256(json.dumps(parse(expression), separators=(",", ":")).encode()).hexdigest()


def compute(expression, fields):
    tree = parse(expression)

    def apply(node):
        if isinstance(node, str):
            return fields[node].copy()
        name, *args = node
        x = apply(args[0])
        if name == "rank":
            return x.rank(axis=1, pct=True)
        if name == "neg":
            return -x
        if name == "abs":
            return x.abs()
        if name == "delay":
            return x.shift(args[1])
        if name == "delta":
            return x - x.shift(args[1])
        if name == "ts_mean":
            return x.rolling(args[1], min_periods=args[1]).mean()
        if name == "ts_std":
            return x.rolling(args[1], min_periods=args[1]).std(ddof=0)
        y = apply(args[1])
        if name == "add":
            return x + y
        if name == "sub":
            return x - y
        if name == "mul":
            return x * y
        return x / y.where(y.abs() > 1e-12)

    return apply(tree).replace([np.inf, -np.inf], np.nan)


@dataclass(frozen=True)
class Proposal:
    name: str
    hypothesis: str
    expression: str

    @classmethod
    def from_dict(cls, item):
        if not isinstance(item, dict) or set(item) != {"name", "hypothesis", "expression"}:
            raise ValueError("proposal requires exactly name, hypothesis, expression")
        if any(not isinstance(v, str) or not v.strip() for v in item.values()):
            raise ValueError("proposal values must be nonempty strings")
        if len(item["name"]) > 80 or len(item["hypothesis"]) > 2000:
            raise ValueError("proposal text exceeds size limits")
        parse(item["expression"])
        return cls(**item)
