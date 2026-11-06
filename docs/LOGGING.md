# Logs and debugging

Where BeamNG.Earth writes what it does, what the lines mean, and how to get more detail for one area without
flooding the log. Players send these files with a bug report. Developers read them first when something goes wrong.

## The files

| File | Written by | Where |
| --- | --- | --- |
| `server.log` (+ `.1`, `.2`: the two runs before) | the world server and its worker processes, plus the game's `game: ...` lines | `<data dir>/logs/` (Windows `%LOCALAPPDATA%\beamng-earth\logs`, Linux `~/.cache/beamng-earth/logs`) |
| `launcher.log` | the launcher | the same folder |
| `beamng.log` | the game, including the mod's `beamngEarth` lines | the game's user folder (`.../BeamNG.drive/current/beamng.log`) |
| session folder | the tiles, blocks and meshes the server made for the game | the game's user folder, `temp/beamngEarth/` |
| reports | the in-game report tool (Ctrl+Shift+E) and profiler (Ctrl+Shift+Y) | the game's user folder, `beamngEarth/reports/` |

The mod's own lines go to both `beamng.log` and `server.log`, so `server.log` alone usually tells the whole story. In
`server.log` they start with `game:`.

Every line has the same shape, in the server and in every worker process:

```
2026-11-06 01:05:42,035 INFO earthd.grading: grading: rail crossing at 39.28340,-76.59340 ...
```

The launcher's console echoes only the warnings and errors (`launcher.echo_lines`). Tools that read `server.log`
depend on this format, so it stays as it is.

## What a log says about its session

The first lines of `server.log` (`logsetup.session_lines`) say what made the log:

```
INFO earthd: session: BeamNG.Earth 1.8.1-beta (packaged app), Python 3.12.7 (CPython, 64bit), pid 9120
INFO earthd: session: Windows 10 (10.0.19045), AMD64, 16 logical CPUs, 31.9 GB RAM (18.2 GB free)
INFO earthd: session: options: cells=64, user_dir='C:\\Users\\...\\BeamNG.drive\\current'
INFO earthd: session: environment: BNGE_DEBUG=grading
INFO earthd: session: debug logging on for earthd.grading
INFO earthd: game hello: mod 0.4.0, protocol 4, format 4
```

- `options` lists only the choices that differ from the defaults.
- `environment` lists the mod's own switches (`BNGE_*`, `BNE_*`, `BNGEARTH_*`). Values with KEY, TOKEN, SECRET,
  PASS, AUTH or COOKIE in their names are hidden.
- `game hello` names the mod version that connected. A protocol mismatch says which protocol this server speaks.
- The game also sends its machine lines (`game: machine: ...`: the GPU, the game version and the graphics settings) and
  `perf ...` lines (perflog.lua: hitches, frame-rate drops and the minute line).

## Crashes and stalls

- An uncaught exception in any thread is logged as `uncaught ... in thread <name>` with its traceback. So is an
  error in an asyncio task that nothing awaited. These used to reach stderr only, with no time or name.
- A native crash (Rust, DuckDB, numpy) writes every thread's stack to `server.log` (faulthandler).
- A block, road tile or far tile still building after a while logs its worker's stacks (blockworker `_stack_watch`).
  A late heartbeat logs the main thread's stack (`earthd` lag report).

## Debug lines for one area

`-v` turns on every debug line in every area, which is too much to read. Name the areas instead:

```
python server/earthd.py --debug grading,surface
BNGE_DEBUG=grading,surface   (in the environment: the launcher passes it on)
BNGE_SERVER_ENV="BNGE_DEBUG=grading"   (the launcher: for the server alone, not the game)
```

Each area is the logger `earthd.<area>`: grading, surface, roads, blockworker, worker, pools, mapdata, dem, imagery,
net, cache, crossings, vegetation, buildings, colormatch, weather, or any other `earthd.<name>` in the code. `all`
is the same as `-v`. The worker processes inherit the setting, so the block and road tile processes log their debug
lines too.

## Graded roads: humps and rail crossings (`earthd.grading`, gradelog.py)

When a map cell's road plans are made, the grader checks them (`gradelog.report_cell`):

```
INFO earthd.grading: grading: rail crossing at -34.97012,138.66001 (cell 14/14590/9878): road 08b2... at 41.20 m,
     track 08b3... at 41.95 m (road -0.75 m), graded hump 0.48 m +2 m from the track, steepest 16 %
INFO earthd.grading: grading: road 08b2... (cell 14/14590/9878) has a 0.62 m hump over 12 m at -34.97101,138.65873
     (104 m along it), steepest 11 %
```

- **Rail crossings.** At every point where a road's plan crosses a railway bed's plan, the line gives the two
  planned heights there. When the road and the track disagree by 0.15 m or more, the ground is blended between them,
  which makes a hump or dip across the track. That case, or an as-graded hump of 0.2 m or more within 20 m of the
  track, is an INFO line. Crossings that match are DEBUG lines.
- **Humps.** A road's planned profile is checked for its largest rise or dip over the chord of plus or minus 6 m.
  One of 0.5 m or more is an INFO line, at most two per cell, with a count of the rest.
- With `--debug grading`, every road gets one line: its length, steepest grade, and largest hump and where it is.
- Coordinates are `lat,lon` to five decimals (about 1 m). The place search takes them as they are (places.parseLatLon),
  so you can paste one in to teleport there.
- Plans that come from the plan cache (a return visit, or another process's plans) are logged only with
  `--debug grading`, so a cell is not logged once per process. To see the lines for a place you have visited before,
  run with `--debug grading`.

## What the car drives on (`game: ground ...`, `game: wheels ...`; diaglog.lua)

The car's grip comes from the physics block's layers. Each 2 m sample has a TerrainMaterial whose ground model
(ASPHALT_OLD, GRASS, DIRT, ...) sets the grip. The DecalRoads drawn on top have no physics. A paved road that drives
like dirt therefore means one of three things: the block's layer under it was not asphalt, the layer's material did
not drive as its ground model, or the car was on another block. These lines tell them apart:

```
game: ground block 512,1024 swap 11 ms, layers Asphalt=ASPHALT_OLD Grass=GRASS Dirt=DIRT at -34.97012,138.66001, 61 mph
game: ground block 514,1024 import 27 ms, layers ...; partial: built before its map cells (its roads drive as the
      land cover until built again) at ...
game: ground block 516,1024 swap 9 ms, layers ...; WRONG: bngEarthGroundAsphalt drives as DIRT, not ASPHALT_OLD at ...
game: ground issue: surface layers unusable (a mask missing or a material not made): the whole block is the single
      dirt layer at ...
game: wheels: ground 10 -> 15 at -34.97012,138.66001, 61 mph, block 512,1024; last block commit 0.4s ago, last
      collision rebuild 3.1s ago; wheels FL=15/4/0.00 FR=15/4/0.00 RL=15/4/0.00 RR=15/4/0.00
game: ground minute (60s): blocks 14 (12 swaps, 2 imports, 1 partial, slowest 31 ms), collision rebuilds 9
      (2 urgent, slowest 24 ms, longest gap 6.1s), wheels 10 82 %, 15 18 % at ...
```

- **`ground block`**: a block was committed, either swapped in from its `.ter` or imported. The line gives how long
  that took, and each layer with the ground model the server asked for. Each layer is checked against the
  TerrainMaterial the engine actually has. A missing layer, one taken by another kind of object, or one with another
  ground model is listed under `WRONG`. `partial` means the server built the block before its map cells arrived (the
  server logs `block ... built before its map cells were here` and, later, `built again with its roads`). Its roads
  drive as the land cover under them until it is built again. A line is written when the layers change, on a problem,
  and for the first block of a connection. Other commits are counted in the minute line.
- **`ground issue`**: terrain.lua fell back to something. The surface layers were unusable, so the block got the
  single dirt layer, or importMaps failed with its materials.
- **`wheels`**: the ground under the player's wheels changed while driving. The mod asks the vehicle's Lua for each
  wheel's `contactMaterialID1` once a second, above 2 m/s. The numbers are the game's ground model ids, not names. A
  change from the usual paved id to another on a paved road is the event to look for. The ages of the last block
  commit and the last collision rebuild show whether the change came right after a block swap (the block's layers)
  or not (the paint under that spot). A game whose vehicle Lua has no such fields logs `ground probe off` once and
  stops asking.
- **`ground files`** (server): when the wheels change ground, the server says what the block's own files hold under the car (the material there and within 4 m, the asphalt share). Grass under a road means the server wrote the block wrong. Asphalt means the game applied it wrong (the swap).
- **`ground minute`**: block commits, collision rebuilds (be:reloadCollision from roads.lua: how many, the slowest,
  the longest gap between two) and the wheels' ground ids by share of the samples.

## BeamNG's own tools while developing

- The console (`~`) shows `beamng.log` live. `dump(obj)` prints a table. Our extensions are `beamngEarth_core`,
  `beamngEarth_roads`, and so on: `beamngEarth_roads.status()` gives the road queue.
- Mod Lua logs with `log('I'|'W'|'E'|'D', 'beamngEarth', text)`.
- Vehicle Lua is a separate Lua state per vehicle. Code runs there through `veh:queueLuaCommand(...)` and answers
  back with `obj:queueGameEngineLua(...)` (diaglog's wheels probe, mpsession).
- The in-game dev tools (docs/DEVTOOLS.md: LOD, loading and collision overlays), the runtime profiler
  (docs/RUNTIME_PROFILER.md) and the report tool (Ctrl+Shift+E) are in the BeamNG.Earth tab of the pause menu.
- Offline: `python tools/run_lua_tests.py` (the mod's Lua against stubs) and `python tools/run_tests.py` (the server).
