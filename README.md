# Conference Badge — IEEE Rising Stars Networking Badge (2026)

A wearable, BLE-based conference badge built around the **ESP32-WROOM-32**. Each badge advertises an attendee's encoded interests while simultaneously scanning for compatible profiles nearby. When two badges match, a proximity LED guides the attendees toward each other, and a shared "pair" color confirms the connection once they meet face to face.

This is the 2026 iteration of the badge developed by the Sensors, Energy and Automation Laboratory (SEAL) at the University of Washington, building on the 2025 IEEE Rising Stars Conference badge.

> **Note on hardware history:** earlier versions of this project (and this README) targeted the Raspberry Pi Pico W. Testing showed the Pico W's BLE range and RSSI stability were not reliable enough for proximity matching, so the project moved fully to the **ESP32-WROOM-32**. Any reference to the Pico W in older files/branches is historical.

## How it works

- **Dual-mode BLE:** every badge advertises its own profile and scans for others at the same time — there's no fixed central/peripheral role. Whichever badge sees the other's advertisement first initiates the connection.
- **Matching:** each badge holds two 10-element integer arrays — one describing itself, one describing who it's looking for — plus a match-tolerance value. When two badges hear each other, they run a bidirectional compatibility check in both directions; a connection only proceeds if both sides agree it's a match.
- **Proximity feedback:** once matched, badges track each other's RSSI (signal strength) and convert it to an estimated distance using a log-distance path-loss model. A dedicated PWM RGB LED shifts from red (far) to green (close) and blinks faster as the badges get closer.
- **Pair confirmation:** a second, simple digital RGB LED lights up in a shared color (assigned randomly per badge, 1–7) so matched attendees can visually confirm they've found the right person.
- **Celebration:** once badges are close enough for two consecutive readings, both play a short color-cycling celebration sequence and the pairing is recorded so the same two badges won't re-match during the same session.

For the full technical writeup — BLE timing, the path-loss model, and the matching algorithm in detail — see the project report.

## Repository Structure

```
current_version/   → active firmware (pcb-no-ui_2.py) — start here
past_versions/      → archived hardware/firmware iterations (Pico W and early ESP32 versions)
examples/            → small standalone scripts (PWM LED demo, BLE scan/service examples)
tests/                → hardware bring-up scripts (switch test, onboard LED test)
ESP32_Wireless_Data_Input.py   → earlier full firmware reference, kept at repo root
ESP32_User_Interface_V1.html   → browser-based badge profile configurator (outputs profile.json)
upload_user_parameters.sh       → USB provisioning script (outputs config.json)
```

**`current_version/pcb-no-ui_2.py` is the authoritative firmware.** It matches the pin mapping and BLE behavior described in the project report. The top-level `ESP32_Wireless_Data_Input.py` is an earlier snapshot kept for reference — it uses a different (older) pin mapping and shouldn't be used for new builds without checking against `current_version/` first.

## Hardware

- **MCU:** ESP32-WROOM-32 (ESP32-DEVKIT-V1 for breadboard prototyping)
- **LEDs:** 2× common-anode RGB LEDs — one PWM-driven (proximity), one digitally-driven (pair color)
- **Switch:** on/off control for advertising & scanning

Pin mapping used by `current_version/pcb-no-ui_2.py`:

| Function | Pin(s) | Notes |
| --- | --- | --- |
| Proximity LED — R / G / B | GPIO 14 / 12 / 27 | PWM, 1 kHz, common anode (active-low duty cycle) |
| Pair LED — R / G / B | GPIO 32 / 33 / 25 | Digital on/off, common anode |
| Pair LED enable | GPIO 26 | Must be driven high for the pair LED to light |
| On/off switch | GPIO 13 | Configured `PULL_UP` |
| Onboard LED | GPIO 2 | Status/debug only |

Full schematics and component rationale (LED and switch part numbers, PCB layout) are covered in the hardware documentation rather than duplicated here — check there before wiring a new board, since a couple of hardware constraints (LED forward voltage vs. rail voltage, resistor sizing) are still being finalized alongside the power source decision.

## Prerequisites

- A computer with **Thonny**, **VS Code** (with a MicroPython/Pymakr extension), or just a terminal with `mpremote`
- The latest **MicroPython firmware for ESP32** (not the Pico W build): https://micropython.org/download/ESP32_GENERIC/
- **aioble** (async BLE library): https://github.com/micropython/micropython-lib — see also the reference docs at https://docs.openmv.io/library/aioble.html#aioble.scan
- **asyncio**: bundled with recent MicroPython builds; see https://docs.micropython.org/en/latest/library/asyncio.html

## Getting Started

1. **Flash MicroPython** onto the ESP32-WROOM-32 using `esptool.py` or Thonny's built-in installer.
2. **Install `aioble`** on the device (via `mip install aioble` over Wi-Fi, or by copying the library files manually if the board isn't networked).
3. **Wire the hardware** per the pin table above (or use the custom PCB — see hardware docs).
4. **Upload the firmware.** Copy `current_version/pcb-no-ui_2.py` to the board as `main.py` so it runs automatically on boot:
```
   mpremote connect auto cp current_version/pcb-no-ui_2.py :main.py
```
5. **Set the attendee profile.** This is currently the main manual step — see below.
6. **Reset the board.** On boot it flashes the pair LED white as a self-test, then starts advertising and scanning.

### Setting a profile (current state)

Two provisioning tools exist in this repo, but neither is wired into the firmware yet:

- `upload_user_parameters.sh` — a USB provisioning script that collects research field, institution, company, and name, and writes them to `config.json` on the device.
- `ESP32_User_Interface_V1.html` — a standalone browser-based configurator that walks through identity, tags, and match tolerance, and exports a `profile.json` with the `info_array` / `find_this` arrays the matching algorithm actually uses.

Right now, `current_version/pcb-no-ui_2.py` does **not** read either file — the attendee's self-tag array, search-tag array, tolerance, and name are hardcoded at the bottom of the firmware in the `main()` function:
```python
badge = Badge([1, 2, 0], [1, 2, 0], 1, "AAAAA")
```
To provision a badge today, edit that line directly before uploading. Wiring a `load_profile()` step that reads `profile.json` on boot — and reconciling it with the `config.json` format produced by the shell script — is the main open item before this can scale past hand-editing each badge.

## Known Limitations

- **Profile loading isn't automated yet** (see above) — this is the current deployment bottleneck.
- **RSSI-based distance is approximate.** It's sensitive to body absorption, walls, and nearby BLE traffic; the two-reading confirmation threshold reduces false positives but doesn't eliminate them.
- **Session history resets on reboot.** The set of already-matched devices is held in RAM only.
- **Multi-badge scale is untested.** Behavior with dozens/hundreds of badges advertising and scanning simultaneously hasn't been validated.

For the day-to-day list of open bugs and their status, see the project's Known Issues documentation rather than this README.

## References

- Project report: *On-Device BLE Matching and Proximity Guidance for Conference Attendee Networking*
- aioble scan/advertise reference: https://docs.openmv.io/library/aioble.html#aioble.scan
- micropython-lib (aioble source): https://github.com/micropython/micropython-lib
- MicroPython asyncio docs: https://docs.micropython.org/en/latest/library/asyncio.html

## Team

Sensors, Energy and Automation Laboratory (SEAL), University of Washington — Olga Podkorytova, Khushal Jain, Leonard Liu, Anthony Li, Sukriti Sehgal, Hudson Wang, Leo Lin.
