# <Skill Name> Skill

## Purpose
<1-3 sentences: what this skill covers and when to reach for it. Include any "prefer this over X"
or "do not use for Y" guidance so the LLM routes correctly.>

## Trigger keyword: <primary_word>

## Interface
- Module: `code/skills/<Folder>/<module_name>.py`
- Functions:
  - `function_one(param: type, param: type = default)`
  - `function_two(param: type)`

## Parameters

### `function_one(param1, param2)`
- `param1` *(required)* - description. Include valid values or format constraints if applicable.
- `param2` *(required)* - description.

### `function_two(param1, param2 = default)`
- `param1` *(required)* - description.
- `param2` *(optional, default X)* - description.

### `no_arg_function()`
No parameters.

## Output
- `function_one(...)` - description of return type and structure.
- `function_two(...)` - description.
- `no_arg_function()` - description.

## Triggers
Invoke this skill when the prompt contains any of these concepts or phrases:
- `phrase or concept`
- `another phrase`

## Scratchpad integration
<Describe whether and how this skill interacts with the scratchpad.
If outputs are large or reused in downstream steps, show the park-then-reference pattern.
If the skill is not a scratchpad candidate, state that clearly and explain why
(e.g. output is a small struct, runs in a subprocess, or is the scratchpad itself).>

## Examples
- `function_one("arg1", "arg2")` - plain English description of what this achieves
  - Returns: `"expected output string"`
- `function_two("arg")` - description of this variant or edge case
  - Returns: `"expected output string"`
