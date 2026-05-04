# Guidelines: When to Split a Physical Device into Multiple vdSDs

> Derived from the digitalSTROM vDC API Properties documentation (§4.1, §4.2, §4.9, §4.10, §5.1, §5.2).

## The One Rule That Forces Splitting

**Each vdSD can have at most ONE output.** If your hardware has multiple
independent output functions (e.g. a dual dimmer, a device with both a light
and a shade motor), each output must be a separate vdSD. Multiple *channels*
on the same output (e.g. brightness + hue + saturation for an RGB light) are
fine within one vdSD — channels are parameters of the output, not separate
outputs.

## Independence Requires Separation

Split into separate vdSDs whenever functional units may need:

- **Different zone assignments** — a vdSD has exactly one `zoneID`.
- **Different primary groups (colors)** — a vdSD has exactly one `primaryGroup`.
- **Independent scene behaviour** — scenes control the single output's channels.

*Example:* A dual 2-way rocker → 2 vdSDs because each rocker might control a
different zone/group.

## What Does NOT Require Splitting

| Component | Allowed Per vdSD | Recommendation | Why? |
|---|---|---|---|
| Button inputs | 0 to many | Single Pushbutton or Pushbuttongroup only | Even though buttons are stored as array with its own group/function setting, configurator UI only allows config for first Button/Buttongroup |
| Binary inputs | 0 to many | Single Binary input per vdsd only | Even though binary inputs are stored as array with individual group settings configurator UI only allows config for first binary input |
| Sensors | 0 to many | 0 to many |Stored as array, no individual sensor settings available |
| Output channels | 1 to many (on the single output) | # of channels normally directly related to outputFunction | setting of outputFunction expects specific number and types for specific outputFunctions  |

A paired up/down rocker (2 buttons) is one vdSD with 2 button inputs at
index 0 and 1.

## dSUID Enumeration for Multi-vdSD Devices

When splitting, use `derive_subdevice()` so all sibling vdSDs share bytes
0–15:

```python
base = DsUid.from_enocean("0512ABCD")
vdsd_light = base.derive_subdevice(0)   # light output
vdsd_shade = base.derive_subdevice(1)   # shade output
```

**Only** do this when the association is **unambiguous and permanent**.
Modules that physically detach and work independently should get fully
distinct dSUIDs (different bytes 0–15).

Sparse enumeration is allowed (e.g. 0, 2 for a dual rocker that could expand
to 0,1 and 2,3).

## Quick Decision Checklist

1. Count independent outputs → one vdSD per output.
2. Can functional units end up in different zones? → separate vdSDs.
3. Do functional units belong to different dS classes (colors)? → separate vdSDs.
4. Multiple buttons/sensors/inputs on the same functional unit → keep in one vdSD.
5. Is the hardware permanently integrated? → use `derive_subdevice()` enumeration.
6. Are parts physically separable? → use fully distinct dSUIDs.
