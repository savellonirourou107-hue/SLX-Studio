# Demo models

## Semantic diff demo

`make_demo_models.m` generates two genuine Simulink SLX files:

- `controller_before.slx`: `Input -> Gain`, with `Gain = 2`
- `controller_after.slx`: `Input -> Gain -> Output`, with `Gain = 3`

```matlab
make_demo_models(pwd)
```

Then:

```bash
slx-diff diff controller_before.slx controller_after.slx --format markdown
```

## Editable + simulation demo

`make_live_demo.m` creates a tiny model that can be loaded and simulated:

```text
Step -> Kp -> Limiter -> Output
                   \-> Monitor (To Workspace)
```

```matlab
make_live_demo(pwd)
```

Then from a shell:

```bash
slx-diff matlab-status
slx-diff studio slxdiff_live_demo.slx
```

In Studio, select **Kp**, stage `Gain: 2 -> 3.5`, then click **Apply in MATLAB** or **Run Simulation**.

The Python test suite uses tiny synthetic SLX ZIP/XML fixtures so contributors can develop without MATLAB. These MATLAB scripts exist to validate the same workflows against files actually written by Simulink.
