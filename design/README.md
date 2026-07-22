# Frozen UI reference

This directory is the reviewed Scholarr UI contract frozen on 2026-07-22.

- `DESIGN.md` is the canonical Vue handoff.
- `tokens.css` is the canonical token layer.
- `component-reference.html` renders the component library from those tokens.
- `assets/` contains the production icon, logo, and favicon inputs.
- `reference/Scholarr.dc.html` is the proof implementation used during design review.
- `reference/support.js` and `reference/uploads/` exist only to render that proof. The support
  runtime must never be included in the production application.

The original reviewed files came from the git-excluded legacy design workspace on tank at
`/opt/stacks/scholarr/design/round2/`. Change the product UI only through an explicit owner-approved
design revision. Implementation work should port this contract, not edit it in place.
