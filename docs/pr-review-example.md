# Example PR review

A model changes from:

```text
Input -> Gain       Gain = 2
```

to:

```text
Input -> Gain -> Output       Gain = 3
```

`slx-diff` summarizes the review as:

```text
1 model inspected · 3 semantic changes

Changed block
  Gain
    Gain: 2 -> 3

Added block
  Output [Outport]

Added connection
  Gain:out1 -> Output:in1
```

The actual GitHub Action output uses Markdown tables and collapsible per-model details; this simplified text is kept in the docs so the core idea is understandable at a glance.
