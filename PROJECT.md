## Project Definition
An exercise in creating an orchestration framework blending LLM and Python calls.
Calling an LLM from Python is easy, this is to call Python from the judgement of an LLM.

## Example Command Lines

### Run a single prompt
```powershell
# Basic usage with default prompt and model
python code/main.py

# Run with a custom prompt
python code/main.py --user-prompt "output the time"

# Run with a different model
python code/main.py --model "llama3:8b" --user-prompt "what is today's date"

# Run with a custom prompt and larger context window
python code/main.py --user-prompt "summarize system health" --num-ctx 8192
```

### Run in interactive chat mode
```powershell
# Start a multi-turn chat session (type 'exit' or 'quit' to end)
python code/main.py --chat

# Chat with a specific model and larger context window to accommodate longer conversations
python code/main.py --chat --model "llama3:8b" --num-ctx 65536
```

### Run the test wrapper
```powershell
# Run with default test prompts
python testcode/test_wrapper.py

# Run with custom prompts
python testcode/test_wrapper.py --prompts "output the time" "what is today's date"

# Run with custom output directory
python testcode/test_wrapper.py --output-dir testcode/results

# Run with both custom prompts and output directory
python testcode/test_wrapper.py --prompts "show system info" "output the time" --output-dir testcode/my_results
```
