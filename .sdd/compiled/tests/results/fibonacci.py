def fib(n):
    """Return the n-th Fibonacci number (0-indexed)."""
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


if __name__ == "__main__":
    N = 10
    for i in range(N):
        print(fib(i))
