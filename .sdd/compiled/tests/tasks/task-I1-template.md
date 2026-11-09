# Task-I1: Generate a Fibonacci sequence script

## Task

Create a self-contained Python (3.x) program file at:

```
.sdd/compiled-tests/results/fibonacci.py
```

The program must implement the Fibonacci sequence and behave as follows:

1. Define a function `fib(n)` that returns the `n`-th Fibonacci number (0-indexed):
   - `fib(0) == 0`
   - `fib(1) == 1`
   - `fib(n) == fib(n-1) + fib(n-2)` for `n >= 2`
2. Under a `if __name__ == "__main__":` guard, compute and print the first `N` Fibonacci
   numbers, one per line, where `N = 10`.
3. The printed output (the only program output) must be the 10 lines:

   ```
   0
   1
   1
   2
   3
   5
   8
   13
   21
   34
   ```

Constraints:
- Pure standard library only; no dependencies.
- Do not run the program (execution/validation is out of scope for you). Just write the file.
- Keep the implementation clear and correct (iterative is fine).

## Deliverable location

Write the resulting file only to: `.sdd/compiled-tests/results/fibonacci.py`

The accepted result must byte-match the reference maintained by the orchestrator under
`.sdd/compiled-tests/expected/fibonacci.py`. The produced content is the sole artifact of this task.

## Justification


