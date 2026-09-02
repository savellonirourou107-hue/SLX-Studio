# SLX patch format

v0.4 introduces a small JSON patch protocol for safe browser/agent edits.

```json
{
  "schema_version": "0.1",
  "model_name": "controller",
  "source_sha256": "64 lowercase hexadecimal characters",
  "operations": [
    {
      "op": "set_param",
      "block_path": "Controller/Kp",
      "parameter": "Gain",
      "before": "2",
      "after": "3.5",
      "sid": "17",
      "system_id": "system_12"
    }
  ]
}
```

## Why include `before` and SHA-256?

A patch is an intent, not permission to overwrite whatever happens to be on disk later. Before launching MATLAB, `slx-diff` verifies:

1. the source file SHA-256 still matches,
2. the target block exists,
3. SID matches when supplied,
4. the named parameter exists,
5. the current canonical value equals `before`.

If any check fails, the patch conflicts and must be regenerated/rebased.

## Current operation set

v0.4 intentionally supports only:

```text
set_param
```

Future versions may add block insertion/removal and rewiring, but those operations need stronger identity and conflict semantics first.
