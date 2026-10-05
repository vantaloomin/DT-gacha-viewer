# DT Gacha Viewer

A local viewer and exporter for the art in **Dragon Traveler**, built from your own copy of the
PC (launcher, non-Steam) client. Browse every hero and outfit; play the animated Spine illustrations
the way the game shows them (fixed phone screen, tap reactions, voice lines); look at portraits,
cards and backgrounds; watch the showcase videos; inspect the 3D battle models with all their
animations; and export stills, animated WebP/GIF, WebM or PNG frames.

**This repository contains no game content.** It is only the viewer and the scripts that extract
content from a client you have installed. Extracted files stay on your machine and are excluded
from git by `.gitignore`. Please don't redistribute them — the art, audio and models belong to the
game's publisher. This is a fan project for personal study, unaffiliated with the developer.

## Requirements

- Windows with the Dragon Traveler PC client installed (the launcher version; the folder that
  contains `DragonTraveler.exe` and `DragonTraveler_Data`, usually `...\DragonTraveler\client`).
  Start the game once and let it finish downloading updates, so the patch files are present.
- [Python](https://www.python.org/) 3.10 or newer, on PATH.
- [FFmpeg](https://ffmpeg.org/) on PATH, built with libopus and libvpx (any "full" Windows build,
  e.g. `winget install Gyan.FFmpeg`).
- Chrome or Edge for the viewer (it uses WebGL and WebCodecs).
- About 6 GB of free disk space for the extracted content.

## Setup

Download the latest zip from [Releases](https://github.com/vantaloomin/DT-gacha-viewer/releases/latest)
(*Source code (zip)*) and unzip it anywhere, or clone the repository:

```bat
git clone https://github.com/vantaloomin/DT-gacha-viewer.git
```

Then double-click **`Update Gallery.bat`**. On the first run it checks for Python, installs the
Python packages and offers to install FFmpeg with winget. It finds the game folder automatically (or
asks for it the first time), then runs every extraction step in order. The first run takes several minutes; later runs only
process files the game has changed, so after a game patch just run it again — the gallery's
"What's new" button lists new heroes and outfits.

Finally double-click **`Open Gallery.bat`** to start a local server and open the gallery in Chrome.
The minimized "Hero Gallery Server" window closes by itself about a minute and a half after you
close the last gallery tab (`python _tools\serve.py 8765 --stay` keeps a server running instead).

If the game folder isn't detected, point the tools at it once:

```bat
python _tools\config.py "D:\Games\DragonTraveler\client"
```

(or set the `DT_GAME_DIR` environment variable).

## Using the gallery

- **Animated** — the hero's Spine illustration inside a landscape phone frame using the game's own
  2340×1080 screen camera. Heroes open in *Interactive* mode: tap the character to trigger the
  reactions the game defines (Settings → *Show tap zones*). Sound is off by default; turn it on with
  the speaker button (or `M`) for greetings and tap voice lines, in Japanese or Chinese.
- **Art** — portrait, card and background, with censored variants where the game has them.
- **Videos** — the in-game showcase intro/loop videos. They wait for Play unless you switch on *Auto-play*.
- **3D Model** — the battle model with every animation clip (idle, run, skills, reactions, story);
  orbit/zoom, lit/toon/unlit lighting. Models hold their idle pose until you press Play or pick a clip
  (Settings → *Auto-play animation* to start them automatically).
- A hero opens on **Art** (or the 3D model, videos or animation, in that order, if it has no art).
- **Export** — still PNG, animated WebP, GIF, WebM or a zip of PNG frames, at up to the game's native
  2340 px, with a transparent or solid background; 3D exports can spin as a 360° turntable.
- **All Spine rigs** (`viewer.html`) — every rig in the game, including goddess rooms, affection
  scenes, events and UI animations.
- Press `?` in the gallery for keyboard shortcuts.

The gallery works offline: `_tools/vendor.py` keeps local copies of the web libraries it needs.

## How it works

Everything is driven by `_tools/update.py`, which runs these steps (each can also be run alone from
the `_tools` folder):

| Step | What it does |
|---|---|
| `index.py` | De-obfuscates the client's Unity bundles (a junk prefix plus decoy `UnityFS` headers; the real header is the one whose size field equals the remaining file length) and records which assets each holds. |
| `build_prefab_dirs.py` | Maps Spine prefab names (as the game's tables refer to them) to extracted folders. |
| `extract.py` | Extracts Spine rigs (`.skel`, `.atlas`, texture pages) and hero images. Patched assets are taken from `local_data/res_update`. Texture pages that Unity resized on import are resized back to the size the atlas declares. |
| `build_names.py`, `make_manifest.py` | English names from the game's SQLite tables (`local_data/db`, `*_Lang` tables); the rig list. |
| `convert_usm.py` | CRI `.usm` videos → WebM (the VP9 stream is copied losslessly; ADX audio and alpha masks are merged). |
| `extract_audio.py` | CRI ADX2 `.acb`/`.awb` banks → Ogg Opus, with its own HCA decoder (FFmpeg's doesn't decode this game's HCA v3 audio correctly). |
| `export_models.py` | Unity skinned meshes, Avatar skeletons and Mecanim animation clips → glTF `.glb`. |
| `build_interactions.py` | The game's tap state machine (`SpineRole`, `SpineRoleClick`, `SpineRoleAct`) and voice cue ids. |
| `build_heroes.py` | `heroes.json`: every hero, outfit, rig, image, video, model and voice. |
| `vendor.py` | Downloads pinned copies of the web libraries into `vendor/`. |

Notes on matching the game's rendering:

- Hero rigs are authored for a fixed 2340×1080 screen centred on the skeleton origin, so the camera
  is that rectangle rather than the animation bounds.
- The game plays `birth` first and loops the other animations, which only key what they move, so
  loops start from `birth`'s final pose, and animation changes are hard cuts (crossfading blends the
  separate scenes of multi-scene outfits together).
- Tap areas in `SpineRoleClick` are `x_y_w_h`: centre and size in skeleton units.

## Third-party libraries

Downloaded by `_tools/vendor.py`, not included in this repository:
[Spine Runtimes](https://github.com/EsotericSoftware/spine-runtimes) (spine-player 4.1; governed by
the Spine Runtimes License), [three.js](https://threejs.org/) (MIT),
[gifenc](https://github.com/mattdesl/gifenc) (MIT), [webm-muxer](https://github.com/Vanilagy/webm-muxer) (MIT),
[JSZip](https://stuk.github.io/jszip/) (MIT/GPLv3) and the [Inter](https://rsms.me/inter/) font (OFL).
Python dependencies: [UnityPy](https://github.com/K0lb3/UnityPy), NumPy, Pillow.

## License

The code in this repository is released under the [MIT License](LICENSE). It covers only this
project's own code — not Dragon Traveler's art, audio, models, names or trademarks, which belong to
the game's publisher, and not the third-party libraries above, which keep their own licences.
