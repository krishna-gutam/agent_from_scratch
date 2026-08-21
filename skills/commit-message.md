---
name: commit-message
description: Turn a diff or a description of changes into a conventional commit message.
---

# Commit message

Write one commit message for the changes the user describes or pastes.

## Format

```
<type>(<scope>): <subject>

<body>
```

- `type` is one of: feat, fix, refactor, perf, test, docs, build, chore.
- `subject` is imperative mood, lower case, no trailing period, under 60 chars.
- `body` is optional. Include it only when the *why* is not obvious from the
  subject. Wrap at 72 chars.

## Rules

- One message, not a menu of options, unless the user asks for alternatives.
- Describe the change, not the file list.
- If the diff clearly does two unrelated things, say so in one line and propose
  the split before writing the message.
- Output the message in a code block and nothing else after it.
