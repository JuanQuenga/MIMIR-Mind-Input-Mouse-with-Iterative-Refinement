# QuadClick: click anything by looking at it

Hands-free mouse clicks for people who cannot use their hands. Boxes on the
screen flicker at different speeds; looking at one picks it.

How one click goes:
1. The screen is cut into up to four boxes. The first step always shows all
   of them, so the whole screen stays reachable. After that, boxes with
   nothing clickable in them are left out. Pick the box holding what you
   want. Repeat. (A first-step box where nothing was detected carries on as a
   plain pixel grid.)
2. When 16 or fewer candidates are left, the view is **enlarged** so the boxes
   and the things in them are big.
3. At the last step (4 or fewer left) every candidate gets **its own box**.
4. The view zooms back out and asks **Left click / Double click / Right
   click / Cancel**. For a text box it asks **Type here / Left click / Right
   click / Cancel**.

Something sitting on the line between two boxes can be picked through either
box.

A short jaw clench undoes the last step. A long one goes back to the start,
or pauses if you are already there.

> **Flicker warning.** The regions flicker at 9–15 Hz. Flicker in this range
> can trigger seizures in people with photosensitive epilepsy. Do not run it
> with or near anyone who has that condition, and say so before any demo.

## Run it

```
pip install -r requirements.txt
```
On Windows you can double-click the numbered `.bat` files instead of typing
the commands below. Each one first closes any QuadClick program left running.
`0_stop_all.bat` does only that.

**1. No headset, keyboard only** (learn the interface)
```
python overlay.py --demo --keys-only
```
`--keys-only` ignores the decoder, so a replay left running can't drive it.
Press the number shown on a box to pick it. `Backspace` undo, `Esc` start
over, `B` two / four choices, `P` pause, `[` / `]` softer / stronger flicker,
`Q` quit.

**2. No headset, real brain data** (develop without hardware)
```
python overlay.py --demo            # terminal 1
python replay_dataset.py            # terminal 2   (--subject 2 is the hard one, --speed 4 is faster)
```
A simulated user "looks" at the green button by playing back g.tec recordings
of a person really looking at that flicker frequency. The data goes through
the same decoder the headset uses.

**3. Live with the Unicorn** (Windows laptop with g.Pype)
```
python overlay.py --demo            # terminal 1; drop --demo to click the real desktop
python run_live_gpype.py            # terminal 2
```
First 40 s: relax your jaw and look at the red dot (calibration). Then look
at a region to pick it. `overlay.py --elements` splits between the real
buttons of the active window instead of using a pixel grid.

**4. The real desktop** (Windows)
```
python overlay.py --keys-only       # hotkeys only: try this first
python overlay.py                   # plus the decoder (run_live_gpype.py in a second terminal)
```
A see-through layer sits over everything and lets mouse clicks fall through.
It starts paused. Hold Ctrl+Alt and press `P` to start or pause, `1 2 3 4` to
pick the box with that number, `Backspace` to undo, `Home` to start over, `B`
for two / four choices, `M` for real buttons / pixel grid, `[` `]` for flicker
strength, `Q` to quit. The clicks at the end are real.

- **Real buttons** (default) asks Windows (UI Automation, the interface screen
  readers use) which buttons, links and menu items the front window, the
  taskbar and any open pop-up menu have. It only knows what a program tells
  Windows about itself.
- **Pixel grid** (`M`, or automatically when fewer than two buttons are found)
  reaches any spot on the screen, in about 5 picks on a full-HD display.
- `--no-menu` skips the click-type question and always left-clicks.
- Only the main display is covered.

**5. With the cloud scan** (optional; needs your own Vultr server)
```
7_setup_vultr_server.bat            # once: installs the scanner on the server
python cloud_check.py               # is it reachable from here, and how fast?
python overlay.py --keys-only --cloud auto      # or launcher 8 / 9
```
Windows can only list buttons that a program describes to it. Games and
picture-heavy apps describe nothing inside their window. With `--cloud auto`,
when the window in front is like that, a picture of just that window goes to
your server, enlarged, and the server finds buttons and icons by looking (the
box-finding half of Microsoft's OmniParser). What it finds is added to what
Windows reported, so the desktop, taskbar and other windows stay selectable.
`--cloud always`, or Ctrl+Alt+M, sends the whole screen on every scan as well.

- The picture is taken **once per click**, when the boxes are worked out, not
  continuously. In a game that keeps moving, the boxes can go stale while you
  are picking; it works best on menus and paused screens.
- The model was trained on ordinary app and web screens. In games it misses
  some things, especially oddly shaped ones. Anything it misses can still be
  reached with the pixel grid: a **short jaw clench (or Backspace) on the
  first step** switches to it, and the same again switches back.
- The picture goes only to your server, over an encrypted connection that is
  checked against the fingerprint in `cloud_settings.json`.
- `cloud_settings.json` holds the access key. Keep it private (`.gitignore`
  already excludes it).
- Needs internet. If the server can't be reached, the pixel grid is used.
- **Delete the server on Vultr when the event ends.** A stopped GPU server is
  still billed.
- The laptop side was tested against a stand-in server; how well the real
  model finds things depends on the program on screen.

**Score the decoder on the dataset**
```
python evaluate_dataset.py          # prints the tables below, saves results.png
python tests/test_core.py
```

## What the dataset says

g.tec SSVEP dataset: 2 subjects × 2 runs × 20 trials, four targets (9, 10,
12, 15 Hz), 8 electrodes at the back of the head. The idle baseline for each
run is taken from the subject's *other* run.

Live decision rule replayed over every trial (40 trials per row):

| Channels | Subject | Right | Wrong | No answer | Time to answer |
|---|---|---|---|---|---|
| All 8 | 1 | 40 | 0 | 0 | 2.4 s |
| All 8 | 2 | 36 | 2 | 2 | 3.9 s |
| 3 that a Unicorn also has (PO7, Oz, PO8) | 1 | 40 | 0 | 0 | 2.3 s |
| 3 that a Unicorn also has | 2 | 22 | 1 | 17 | 4.4 s |

- False selections while the subject rested: 0–2 per ~140 s.
- Fixed 3 s window, all 8 channels: plain CCA 85% → idle-corrected 95%
  (subject 2: 73% → 90%). g.tec's own reference result for subject 2 is about
  85% with a trained classifier.
- Simulated full click: 3 selections (≈64 buttons, element mode) take about
  10 s for subject 1 and 15 s for subject 2; a pixel grid on a full-HD screen
  needs 5 selections, 17 s and 24 s.

What this means: some people give a strong signal and some a weak one. With
only three back-of-head electrodes the weak subject mostly gets "no answer"
rather than wrong answers. Calibrate each teammate and demo with the strongest.

Caveats: two subjects and 80 trials is a small sample. The two thresholds
were picked after looking at this same data, so expect live numbers to be a
bit worse.

## What has and hasn't been tested

Tested (in a headless Linux environment):
- Decoder on the dataset (numbers above).
- Whole loop: dataset → engine → UDP → overlay → clicks on demo buttons.
  Subject 1: 10/10 targets hit, 3 selections each, no undo needed.
- The g.Pype pipeline with g.Pype's generator, and with dataset data fed
  through `gp.CsvReader` into `DecoderNode` (picked 12, 9, 15, 10 Hz correctly).
- Jaw-clench detector on synthetic bursts; zero false clenches across all
  four real recordings.

Not tested, check these first at the event:
- **The Unicorn itself.** `gp.HybridBlack` builds and connects here but there
  was no headset. Confirm the data is in microvolts and the channel order is
  Fz C3 Cz C4 Pz PO7 Oz PO8.
- **Real jaw clenches.** The dataset has none. Watch the scope, clench, and
  adjust `CLENCH["k"]` in `bci/config.py` if needed.
- **Windows-only parts not yet confirmed**: real-button detection (UI
  Automation), the screen picture used for enlarging, double and right click,
  pop-up menu detection, screen scaling (125%/150%), and `0_stop_all.bat`.
  The see-through layer, hotkeys and left click were reported working on one
  PC. The logic around all of them was tested with the Windows calls swapped
  out.
- **Screen flicker vs. LEDs.** The dataset used LEDs. A monitor gives a weaker
  signal, and small regions deep in the split weaker still. If deep levels are
  unreliable, raise `--fill`, or make each level zoom to full screen.

## Files

| File | What it does |
|---|---|
| `overlay.py` | The on-screen regions, zooming, undo, click, demo screen |
| `replay_dataset.py` | Simulated user driven by the g.tec recordings |
| `run_live_gpype.py` | Unicorn → g.Pype → `DecoderNode` → overlay |
| `evaluate_dataset.py` | Offline scoring and `results.png` |
| `send_cmd.py` | Send a command to the overlay by hand |
| `bci/config.py` | Every setting worth tuning |
| `bci/ssvep.py` | The SSVEP decoder (CCA + idle baseline) |
| `bci/clench.py` | Jaw-clench detector |
| `bci/engine.py` | EEG chunks in, commands out |
| `bci/splitter.py` | How an area is cut into regions |
| `bci/elements.py` | Finds real buttons via Windows UI Automation |
| `bci/cloud.py`, `cloud_check.py` | Laptop side of the cloud scan |
| `cloud/server.py`, `cloud/setup_server.sh` | The scanner that runs on the Vultr server |
| `bci/keyboard.py` | The on-screen keyboard: layout, word suggestions |
| `bci/winutil.py` | Global hotkeys, the real click, front-window check (Windows) |

The decoder and the overlay only talk over UDP text messages on localhost
(`SEL 2 4.10`, `CLENCH_SHORT`, `LAYOUT …`), so two people can work on them
separately.

## Typing

"Type here" clicks the text box and opens an on-screen keyboard. Keys are
picked exactly like buttons: pick the block, then the key (about 3 picks per
letter with four choices, 5 to 6 with two). The text is built up at the top
of the keyboard and only typed into the program when **Type it** (or **Type
it + Enter**) is picked, so mistakes are fixed before anything is sent.

- Three suggested words (blue keys) follow what has been typed so far.
- A short jaw clench on the keyboard's first step deletes the last letter.
- **123** switches to digits and symbols; **Cancel** closes without typing.
- `T` (Ctrl+Alt+T on the desktop) opens the keyboard for whatever already
  has the typing cursor. Use it for text areas Windows does not report as
  text boxes, such as a document's main editing area.
- Windows only reports classic text fields as text boxes. Typing itself has
  not yet been confirmed on a real Windows program.

## Two choices or four

`B` (or `--choices 2`) switches to two boxes per step, flickering at 9 and
15 Hz. The boxes are bigger and there is less to tell apart, but a click takes
more picks: with 40 buttons, about 8 picks against 4 (both counts include
the click-type question). On the dataset every pair of speeds did about as
well as four-way picking for the strong subject; for the weak subject, pairs
gave 0-1 wrong picks in 20 trials against 2 in 40 with four choices. That is
too few trials to call a difference. Try both on each person.

## Box sizes

By default every box at a level is the same size (`--split equal`). A button
belongs to the box that holds its middle, and boxes with no buttons don't
flicker. `--split balanced` cuts between buttons instead: about half a pick
fewer per click, but the boxes come out uneven and smaller.

| Buttons on screen | Equal: picks to reach one button | Balanced |
|---|---|---|
| 20 | 2.8 | 2.4 |
| 40 | 3.4 | 3.0 |
| 64 | 3.8 | 3.0 |

(Splitting only, measured before the enlarged last step and the click-type
question were added.)

## Comfort

- By default each big box has a quiet outline and a **checkered circle** in
  its middle. The dark and light squares swap places 9 to 15 times a second,
  so the overall brightness never changes. Look at the circle of the box that
  holds what you want. At the last step, where each box sits around a single
  icon, the whole (small) box flickers and you look straight at the icon.
  `C` cycles checkered circles / plain circles / whole-box flicker
  (`--stim checker|circle|full`).
- The flicker stops completely during calibration and while paused.
- After every pick it fades in over 0.6 s instead of starting at full strength.
- Pause: press `P`, or hold a jaw clench while on the full screen. Hold again
  to carry on. (Deeper in, a held clench still means "back to full screen".)
- Softer flicker: `[` and `]` in the demo, or `--contrast 0.6` on the command
  line. Softer is gentler but gives a weaker brain signal. Find the lowest
  setting that still picks reliably for each person.
- `--fill 0` flickers only the frame, so the content inside stays readable.
- The flicker is a smooth sine wave, not a hard on/off blink.

## Tuning

- More wrong picks than you like → raise `thr_score` / `thr_margin`.
- Too slow or too many "no answer" → lower them, or lengthen calibration.
- US mains is 60 Hz (`MAINS_HZ`); the dataset replay uses 50 Hz by itself.
