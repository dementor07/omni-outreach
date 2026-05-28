# Python: The Ultimate Complete Guide

This guide is designed to take you from a basic understanding to the absolute depths of Python's architecture, memory management, and advanced features. 

> [!TIP]
> **The Zen of Python**
> Before writing code, run `import this` in a Python REPL. It outlines the core philosophy: "Beautiful is better than ugly. Explicit is better than implicit. Simple is better than complex."

---

## 1. How Python Works Under the Hood

Python is an interpreted language, but that's a simplification. It is actually **compiled to bytecode** which is then interpreted by the Python Virtual Machine (PVM).

### CPython and the GIL
The reference implementation of Python is **CPython** (written in C). 
> [!WARNING]
> **The Global Interpreter Lock (GIL)**
> CPython has a GIL, a mutex that protects access to Python objects, preventing multiple native threads from executing Python bytecodes at once. This means multithreading in Python does *not* give you true parallelism for CPU-bound tasks. It is only useful for I/O-bound tasks. For true parallelism, you must use multiprocessing.

### Memory Management & Variables
Variables in Python are **not** buckets containing values. They are **labels (references)** pointing to objects in memory.

```python
x = 500
y = 500
print(x is y) # False! They are distinct objects in memory.

a = 10
b = 10
print(a is b) # True! Python caches small integers (-5 to 256) for optimization.
```

**Garbage Collection:** Python uses two mechanisms to free memory:
1. **Reference Counting:** Every object keeps a count of how many variables point to it. When it drops to 0, it is deallocated.
2. **Generational Garbage Collector:** Cleans up cyclic references (e.g., Object A points to Object B, and Object B points to Object A) which reference counting cannot catch.

---

## 2. Mutability vs Immutability

This is the most critical concept to avoid bugs in Python.
- **Immutable Types:** `int`, `float`, `str`, `tuple`, `frozenset`. Once created, they cannot be changed. Modifying them creates a *new* object.
- **Mutable Types:** `list`, `dict`, `set`. They can be changed in place.

> [!CAUTION]
> **The Mutable Default Argument Trap**
> Never use a mutable type as a default argument in a function.
> ```python
> # BAD
> def add_item(item, my_list=[]):
>     my_list.append(item)
>     return my_list
> # The list is evaluated ONCE at function definition. 
> # Subsequent calls share the SAME list!
> 
> # GOOD
> def add_item(item, my_list=None):
>     if my_list is None:
>         my_list = []
>     my_list.append(item)
>     return my_list
> ```

---

## 3. Advanced Data Structures Internals

### Dictionaries (`dict`)
Dictionaries are the backbone of Python (even object attributes are stored in a `__dict__`). 
- Internally, they are **Hash Maps**. 
- Looking up a key `my_dict['key']` is **O(1)** time complexity on average.
- Since Python 3.7, dictionaries maintain insertion order.

### Lists (`list`)
- Internally, they are **Dynamic Arrays** of pointers (not linked lists).
- Appending `list.append()` is **O(1)**.
- Inserting at the beginning `list.insert(0, item)` is **O(N)** because all other elements must be shifted. If you need queue behavior, use `collections.deque`.

---

## 4. Functions, Scopes, and Closures

Python resolves variables using the **LEGB Rule**:
1. **L**ocal (inside the current function)
2. **E**nclosing (inside enclosing functions, for closures)
3. **G**lobal (top level of the module)
4. **B**uilt-in (Python's built-in namespace)

### Closures
A closure occurs when a nested function remembers the state of its enclosing scope even when the enclosing function has finished executing.

```python
def multiplier_factory(factor):
    def multiplier(number):
        return number * factor # 'factor' is captured from the enclosing scope
    return multiplier

times_two = multiplier_factory(2)
print(times_two(5)) # Outputs 10
```

### Decorators
Decorators are just syntactic sugar for higher-order functions (functions that take functions as arguments and return functions).

```python
import time
from functools import wraps

def timer_decorator(func):
    @wraps(func) # Preserves the original function's metadata (__name__, docstring)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"{func.__name__} took {end - start:.4f} seconds")
        return result
    return wrapper

@timer_decorator
def heavy_computation():
    return sum(i * i for i in range(1000000))
```

---

## 5. Object-Oriented Deep Dive

### Dunder (Magic) Methods
Dunder methods (double underscore) allow your classes to interact with Python's built-in operations.
- `__init__(self)`: The initializer.
- `__new__(cls)`: The actual constructor. It returns the instance. Used rarely, mostly in singletons or subclassing immutable types.
- `__str__(self)`: Human-readable string representation (called by `print()`).
- `__repr__(self)`: Unambiguous representation, useful for debugging.
- `__call__(self)`: Allows an instance to be called like a function.

### Method Resolution Order (MRO)
Python supports multiple inheritance. The MRO determines the order in which base classes are searched for a method. It uses the **C3 Linearization** algorithm. You can view it using `MyClass.mro()`.

### Metaclasses
> [!NOTE]
> "Metaclasses are deeper magic than 99% of users should ever worry about." - Tim Peters

A class defines how an instance behaves. A **metaclass** defines how a *class* behaves. `type` is the default metaclass. You can use metaclasses to automatically alter classes when they are created (e.g., automatically registering subclasses in a registry).

---

## 6. Iterators, Generators, and `yield`

An **Iterator** is an object that implements `__iter__()` and `__next__()`. 
A **Generator** is a simpler way to create an iterator using a function with the `yield` keyword.

Generators evaluate lazily. They do not store all values in memory, making them perfect for infinite sequences or massive datasets.

```python
def read_huge_file(file_path):
    with open(file_path, 'r') as f:
        for line in f:
            yield line.strip() # Yields one line at a time, keeping memory usage ~0

for line in read_huge_file("100_GB_log.txt"):
    process(line)
```

---

## 7. Asynchronous Python (`asyncio`)

Asyncio uses an **Event Loop** to run coroutines concurrently on a *single thread*. This is ideal for network I/O, web scraping, and database queries (like in FastAPI).

When a coroutine hits an `await` statement, it yields control back to the Event Loop, allowing the loop to run other tasks while waiting for the I/O operation to finish.

```python
import asyncio

async def fetch_data(id):
    print(f"Fetching {id}...")
    await asyncio.sleep(1) # Simulates network I/O. Yields control to Event Loop!
    print(f"Done {id}")
    return {"id": id, "data": "value"}

async def main():
    # Run multiple coroutines concurrently
    tasks = [fetch_data(1), fetch_data(2), fetch_data(3)]
    results = await asyncio.gather(*tasks)
    print(results)

asyncio.run(main())
```

---

## 8. Type Hinting

Since Python 3.5, type hints allow static analysis (using tools like `mypy`) in a dynamically typed language. This is heavily used in `pydantic` and `FastAPI` (which powers omni-outreach).

```python
from typing import List, Optional, Callable

def process_data(data: List[int], callback: Optional[Callable[[int], None]] = None) -> float:
    total = sum(data)
    if callback:
        callback(total)
    return float(total)
```

In modern Python 3.10+, you can use `|` for unions:
`def process(data: list[int] | None) -> float:`

---
*This document serves as the absolute masterclass on Python's core mechanics. Refer back to it when reading the omni-outreach backend codebase.*
