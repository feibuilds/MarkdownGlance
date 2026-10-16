# Fenced code

Each fence below names its language, and is coloured the way the editor
colours it inside this file.

```python
def hello_world(name: str = "World") -> None:
    """Greet someone."""
    print(f"Hello, {name}!")  # issue 7
    return None
```

```js
const greet = (name) => `Hello, ${name}!`;
export default { greet, answer: 42 };
```

```sh
for f in *.md; do
    echo "$f"
done
```

```json
{"enable_syntax_highlighting": true, "table_max_columns": 200}
```

- A fence inside a list item:

    ```diff
    - plain
    + coloured
    ```

````python
fence = """
```
not the end of the block
```
"""
````

```
No language: shown plain.
```

```nosuchlanguage
Unknown to the editor: shown plain.
```
