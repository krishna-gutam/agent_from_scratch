import json
import math

from .decorator import tool


@tool(
    "Evaluate a mathematical expression, such as '2 + 2', 'sqrt(16)', or 'sin(pi/2)'."
)
def calculate(expression: str) -> str:
    allowed_names = {
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "pi": math.pi,
        "e": math.e,
        "abs": abs,
        "round": round,
    }

    result = eval(
        expression,
        {"__builtins__": {}},
        allowed_names,
    )

    return json.dumps({"result": result})
