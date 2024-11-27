#Scripting Aider
```python
from aider.coders import Coder
from aider.models import Model

# This is a list of files to add to the chat
fnames = ["greeting.py"]

model = Model("gpt-4o-mini")

# Create a coder object
coder = Coder.create(main_model=model, fnames=fnames)

# This will execute one instruction on those files and then return
coder.run("make a script that prints hello world")

# run the tests
coder.run("/run pytest")

coder.run("fix the tests")

```