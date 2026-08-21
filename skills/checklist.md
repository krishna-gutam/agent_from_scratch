# Review checklist

Correctness
- Off-by-one and boundary conditions on every index or slice
- Empty / None / zero-length inputs
- Return values that differ by branch in type, not just value

Failure modes
- Bare `except:` or `except Exception` that hides the cause
- Network and file calls without a timeout or without a failure path
- Resources opened but not closed on the error path

State
- Mutable default arguments
- Module-level state written from more than one place
- Caches that are never invalidated

Interfaces
- Function does two unrelated things
- Arguments that are silently ignored
- Error strings returned where an exception is expected (or vice versa)

Security
- User input reaching `subprocess`, `eval`, or a SQL string
- Secrets read from source instead of the environment
- Paths built from user input without normalisation
