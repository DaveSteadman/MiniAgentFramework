# CodeExecute Skill

## Purpose
Execute a Python code snippet in a sandboxed environment and return the captured stdout as a string - use when the user requests computed or generated data (sequences, tables, calculations) that no other skill can produce. Only Python stdlib modules are available (math, itertools, collections, datetime, json, csv, re, statistics, etc.) - third-party packages such as numpy, pandas, sympy, and scipy are not available; always write self-contained stdlib code.

## Interface
- Module: `code/skills/CodeExecute/code_execute_skill.py`
- Function: `run_python_snippet(code: str)`

## Input
- `run_python_snippet(code: str)`
  - `code`: a complete, self-contained Python snippet.
  - The snippet must use print() to emit all output - the return value of the last
    expression is not captured, only printed lines.
  - Imports are restricted to a safe stdlib whitelist when sandbox is enabled (default): math, itertools, collections, csv, io,
    json, re, random, statistics, datetime, decimal, fractions, functools,
    operator, string, textwrap, heapq, bisect, array, calendar, time, cmath.
  - os, sys, subprocess, open, eval, exec, and file I/O are blocked when sandbox is enabled.
  - Sandbox state can be toggled at runtime with `/sandbox on|off`.
  - Execution timeout: 15 seconds.

## Output
- Captured stdout as a plain string.
- If the snippet raises an exception or produces no output, returns an error string starting
  with `"Error:"`.

## Typical trigger phrases (select this skill for any of these concepts)
- `compute`, `calculate`, `generate a sequence`, `generate numbers`
- `prime numbers`, `fibonacci`, `factorial`, `sequence of`
- `produce a table`, `make a table of`, `create a list of numbers`
- `formula`, `arithmetic`, `statistics`, `series`
- Any prompt requesting *generated* numeric or structured data that needs to be computed

## Tool-calling guidance
When this skill is selected alongside FileAccess, the model will make two sequential tool calls:
1. `run_python_snippet(code=<snippet>)` - generates the data; the model receives the captured stdout.
2. FileAccess write with the captured output as the file content.
The snippet should build the full file content (including any headers) and print it to stdout.
For CSV output, the snippet should print header and rows using print().

## Examples
- `run_python_snippet(code="import math\nfor i in range(1, 6):\n    print(i, math.factorial(i))")`
- `run_python_snippet(code="print('index,prime,fib')\n# ... full snippet ...")`
