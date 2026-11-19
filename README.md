# route6
Step-by-step 6-layer routing helpers for the humbucker preamp board. Start with `REVIEW.md`.

    pip install -r requirements.txt
    python -m pytest -q tests                 # about 3 minutes
    python via_justify.py tests/board_4layer_rev1.kicad_pcb
    python stage_route.py setup --from ../../../humbucker-preamp.kicad_pcb
    python stage_route.py 2b                  # then 2c; steps 2a, 2d, 2e, 2f also need ROUTER_DIR (KiCadRoutingTools)

Everything is written to `work/`. The project board is only read.
