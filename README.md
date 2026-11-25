<div align="center">

# Pioneer AVR for Home Assistant

**Local control for the Pioneer VSX-827 over its native Ethernet interface.**

No cloud. No serial adapter. Just Home Assistant and TCP port `8102`.

[![Release](https://img.shields.io/github/v/release/JoKeks2023/Pioneer-AVR-Homeassistant?style=for-the-badge&logo=github&color=2ea44f)](https://github.com/JoKeks2023/Pioneer-AVR-Homeassistant/releases/latest)
[![Validation](https://img.shields.io/github/actions/workflow/status/JoKeks2023/Pioneer-AVR-Homeassistant/validate.yml?branch=main&style=for-the-badge&label=validation)](https://github.com/JoKeks2023/Pioneer-AVR-Homeassistant/actions/workflows/validate.yml)
[![Home Assistant](https://img.shields.io/badge/Home_Assistant-2024.12%2B-18BCF2?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white)](https://hacs.xyz/)
[![License](https://img.shields.io/github/license/JoKeks2023/Pioneer-AVR-Homeassistant?style=for-the-badge&color=blue)](LICENSE)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JoKeks2023&repository=Pioneer-AVR-Homeassistant&category=integration)

[Features](#features) · [Installation](#installation) · [Setup](#receiver-setup) · [Troubleshooting](#troubleshooting) · [Protocol](#protocol-and-hardware-notes) · [Development](#development)

</div>

---

Pioneer AVR represents the VSX-827 as a proper Home Assistant **AV receiver**.
It creates one main-zone `media_player` entity with the receiver device class,
automatic SSDP discovery, a UI config flow, immediate TCP state updates, and a
30-second fallback refresh.

> [!IMPORTANT]
> **Network Standby** is recommended for network power-on. If the receiver
> deliberately drops off the network when switched off, the integration can
> keep its entity available with the correct `off` state instead of showing
> `unavailable`.

## At a glance

| | |
| --- | --- |
| **Supported receiver** | Pioneer VSX-827 / VSX-827-S |
| **Connection** | Local Ethernet, persistent TCP |
| **Default port** | `8102` |
| **Home Assistant entity** | `media_player` with `receiver` device class |
| **Zones** | Main zone only |
| **Minimum Home Assistant** | 2024.12 |
| **Cloud account** | Not required |
| **Additional hardware** | Not required |

## Features

| Capability | Support | Notes |
| --- | :---: | --- |
| Power on and off | ✅ | Powered-off receivers can remain represented as `off` |
| Volume display | ✅ | Normalized to Home Assistant's `0.0–1.0` range |
| Volume up and down | ✅ | Native `VU` / `VD` commands, 1 dB per step |
| Volume slider / exact volume | ✅ | Reached with confirmed 1 dB steps; at most +10 dB per change |
| Mute and unmute | ✅ | State is queried and confirmed |
| Current input | ✅ | Receiver-reported source |
| Input selection | ✅ | Confirmed Pioneer source codes |
| Listening-mode groups | ✅ | Auto/Direct, Standard/ALC, Advanced Surround |
| Current listening-mode name | ⚠️ | VSX-827 returns only a generic acknowledgement |
| Automatic discovery | ✅ | Precise model/manufacturer SSDP match |
| Options, reconfiguration and diagnostics | ✅ | Host is redacted from diagnostics |
| Speaker B as Zone 2 | — | Not an independent VSX-827 zone |
| Media playback controls | — | Not part of the receiver control protocol |

Supported source names include CD, Tuner, DVD, TV, SAT/CBL, Video, DVR/BDR,
iPod/USB, BD, Adapter Port, Internet Radio, Pandora, Media Server, Favorites,
AirPlay, DMR, and Game. AirPlay and DMR can be reported as the active source,
but the Pioneer protocol does not allow selecting them with an `FN` command.

## Installation

### HACS — recommended

Use the button below to open this custom repository directly in HACS:

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JoKeks2023&repository=Pioneer-AVR-Homeassistant&category=integration)

Alternatively, add it manually:

1. Open **HACS → Integrations**.
2. Open the three-dot menu and select **Custom repositories**.
3. Add the following URL with category **Integration**:

   ```text
   https://github.com/JoKeks2023/Pioneer-AVR-Homeassistant
   ```

4. Download **Pioneer AVR**.
5. Restart Home Assistant completely.

Already installed? Use **Redownload** in HACS to select a newer release, then
restart Home Assistant.

### Manual

1. Download the
   [latest release](https://github.com/JoKeks2023/Pioneer-AVR-Homeassistant/releases/latest).
2. Copy `custom_components/pioneer_avr` to the `custom_components` directory
   inside the Home Assistant configuration directory.
3. Restart Home Assistant completely.

## Receiver setup

1. Connect the VSX-827 by Ethernet to a network reachable from Home Assistant.
   The receiver and Home Assistant do not have to share a subnet; routed TCP
   connectivity to port `8102` is sufficient for manual configuration.
2. Create a stable DHCP reservation for the receiver.
3. Enable **Network Standby** if network power-on is required. Some receivers
   still disable their network interface when off; the integration can retain
   a correct `off` state in that case.
4. Close Pioneer ControlApp. The VSX-827 accepts **only one** control
   connection on port `8102`; while Home Assistant is connected, ControlApp
   and other tools are refused, and vice versa.
5. In Home Assistant, open **Settings → Devices & services**. Accept the
   discovered receiver, or select **Add integration** and search for
   **Pioneer AVR**.
6. For manual setup, enter the receiver's hostname or IP address and port
   `8102`.

[![Open your Home Assistant instance and start setting up Pioneer AVR.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=pioneer_avr)

The setup flow opens a local TCP connection and requires a valid Pioneer power
response before it creates the config entry. YAML configuration is not used.

## Receiver options and volume-display calibration

Open **Settings → Devices & services → Pioneer AVR → Configure**.

### Preserve the powered-off state

Keep **Show as off when unreachable after power-off** enabled if the VSX-827
shuts down its network interface. After Home Assistant successfully sends the
power-off command, the entity remains available as `off`. A receiver that
disappears while its last known state was `on` is still marked unavailable, so
ordinary network failures are not hidden.

If Home Assistant restarts while the configured receiver is unreachable, this
option also allows the existing entity to load as an assumed `off` receiver.
Disable the option if every unreachable state should instead be treated as a
setup failure.

### Two-point volume-display calibration

Pioneer reports volume in raw half-steps, while Home Assistant requires a
normalized `0–100 %` value. Calibration maps the displayed percentage to the
part of the receiver's range that is actually useful for your room:

1. Enable **Calibrate displayed volume range** and submit the options form.
2. Set the receiver manually to the level that should display as `0 %`, then
   submit the first calibration step.
3. Set the receiver manually to the level that should display as `100 %`,
   then submit the second step.
4. The integration reloads and maps the captured endpoints to `0 %` and `100 %`.

The assistant only sends state queries during calibration. It never changes
the volume itself. Calibration defines which receiver levels the volume slider's
`0 %` and `100 %` correspond to.

## How it works

```text
Home Assistant  ⇄  persistent TCP connection on port 8102  ⇄  Pioneer VSX-827
```

Commands are CR-terminated Pioneer protocol messages. Replies and unsolicited
updates may use CR or LF separators. Requests are serialized so that an
incoming state update cannot be mistaken for the reply to another command.
Connection loss, timeouts, malformed responses, and reconnects are handled by
the integration's built-in asynchronous client.

The VSX-827 accepts a single control connection. Home Assistant keeps it open
for immediate updates, enables TCP keepalive, and drops and reopens the
connection as soon as the receiver stops answering, so a stale connection does
not block the receiver.

The tested VSX-827 ignores the documented direct `nnnVL` exact-volume command,
also after a wake CR. One `VU` or `VD` moves the raw value by exactly two
half-steps (1 dB), and steps sent 100 ms apart are all applied. The volume
slider therefore computes the number of 1 dB steps, sends them, re-reads the
actual volume, and corrects from the measured value (never by blindly repeating
a step). A single change raises the volume by at most 10 dB. Volume up and down
each send exactly one native command.

Power-on sends a bare CR to wake the receiver, then `PO`, and confirms the
result with `?PWR` (up to three attempts).

Listening-mode selection mirrors the three buttons in Pioneer ControlApp:

- **Auto / Direct** — `0005SR`
- **Standard / ALC** — `0010SR`
- **Advanced Surround** — `0100SR`

The receiver returns only `R` to tested mode-status queries, so Home Assistant
does not display a potentially incorrect current mode. Selecting a group may
cycle between modes depending on the source and incoming audio signal.

## Automatic discovery

The VSX-827 advertises itself as a UPnP MediaRenderer. The integration uses a
specific combination of values from its device description:

| UPnP field | Expected value |
| --- | --- |
| Manufacturer | `PIONEER CORPORATION` |
| Model | `VSX-827/SYXE8` |
| IP remote ready | `1` |
| TCP port | `8102` |
| Identity | Stable UPnP UUID |

This prevents generic MediaRenderers from being offered as Pioneer receivers.
The UUID provides a stable config-entry identity, while rediscovery can update
a changed IP address.

SSDP is multicast discovery and normally stays inside its local network
segment. A static route that carries unicast TCP does not automatically relay
SSDP between a FRITZ!Box network and a UniFi network. In routed installations,
automatic discovery may therefore be absent even though manual IP setup and
all receiver controls work normally.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| **Invalid handler specified** | Install version `0.1.1` or newer through HACS and restart Home Assistant completely |
| Receiver is not discovered across routed networks | Expected unless SSDP multicast is relayed; use manual IP configuration |
| Connection fails while off | Enable Network Standby for power-on, or enable the preserved `off` option |
| Port `8102` refuses connections | The receiver accepts only one connection: close Pioneer ControlApp, or disable the integration while using other tools |
| Power-on fails but other controls work while on | Network Standby is disabled or the network interface sleeps |
| Home Assistant volume percentage feels wrong | Calibrate the displayed range under **Configure**; this affects display only |
| Volume slider stops short of a high target | Intended: one change raises the volume by at most 10 dB; move it again |
| Sound-mode field has no active value | Expected: the VSX-827 does not report the current mode over TCP |
| An input is shown but cannot be selected | AirPlay and DMR are reportable but not selectable through `FN` |

Enable focused debug logging if needed:

```yaml
logger:
  logs:
    custom_components.pioneer_avr: debug
```

Logs include connection failures and response categories, but not the
configured host or complete raw traffic. Downloadable diagnostics redact the
host as well. When reporting a problem, attach the diagnostics and the relevant
`pioneer_avr` log entries to a
[GitHub issue](https://github.com/JoKeks2023/Pioneer-AVR-Homeassistant/issues).

## Debug tool and hardware validation

The standalone tool uses the exact same asynchronous client as the Home
Assistant integration. Home Assistant itself is not required to run it.

Query the receiver:

```bash
python3 scripts/debug_receiver.py 192.0.2.10 --query
```

Send a documented raw command:

```bash
python3 scripts/debug_receiver.py 192.0.2.10 --command '?PWR' --expect PWR
```

Run guarded state-changing validation:

```bash
python3 scripts/debug_receiver.py 192.0.2.10 --validate
```

Validation records the initial state, verifies each operation with a fresh
query, and restores the original power, mute, and selectable input in a
`finally` block. Keep speakers and connected equipment in a safe state during
hardware testing.

## Protocol and hardware notes

<details>
<summary><strong>Verified command table</strong></summary>

| Function | TCP command | Reply | Status |
| --- | --- | --- | --- |
| Power on/off | `PO` / `PF` | `PWR0` / `PWR1` or `PWR2` | Implemented |
| Power query | `?PWR` | `PWRn` | Implemented |
| Volume up/down | `VU` / `VD` | `VOLnnn` | Implemented |
| Exact volume | `nnnVL` | Ignored (generic `R`) | Emulated with confirmed `VU`/`VD` steps |
| Volume query | `?VOL` | `VOLnnn` | Implemented |
| Mute on/off | `MO` / `MF` | `MUT0` / `MUT1` | Implemented |
| Mute query | `?MUT` | `MUTn` | Implemented |
| Select input | `nnFN` | `FNnn` | Implemented |
| Input query | `?FN` | `FNnn` | Implemented |
| Listening-mode groups | `0005SR`, `0010SR`, `0100SR` | Generic `R` | Selection only |
| Independent Zone 2 | Model dependent | Model dependent | Not available on VSX-827 |

</details>

<details>
<summary><strong>Research findings and sources</strong></summary>

The VSX-827 has Ethernet, AirPlay, DLNA, Internet Radio, and Pioneer ControlApp
support. Its rear-panel connections include Ethernet but no physical RS-232
connector. Pioneer describes its 2012 external command set as common to IP
control and RS-232C; the VSX-827 uses that syntax directly over TCP port `8102`.
No serial cable, USB adapter, or cloud service is involved.

Speaker B is not an independently powered, sourced, and volume-controlled Zone
2 on this model, so the integration intentionally creates only one main-zone
entity.

Sources:

- [Pioneer VSX-827 product information](https://www.pioneer-audiovisual.de/uk/node/408/)
- [Pioneer VSX-827/527 operating manual](https://www.homesound.ro/manuals/VSX-527-827.pdf)
- [VSX-827 TCP port 8102 field report](https://homematic-forum.de/forum/viewtopic.php?f=31&start=30&t=12267)
- [2012 Pioneer IP and RS-232 command-document summary](https://www.scribd.com/document/621112255/Elite-Pioneer-Fy13avr-Ip-Rs-232-5-8-12-1)
- [VSX-1022 protocol-family transcript](https://github.com/schaffman5/VSX-1022_Commands/blob/master/Pioneer_VSX-1022_Commands_2012.txt)
- [Home Assistant Pioneer integration](https://www.home-assistant.io/integrations/pioneer/)

Live VSX-827 validation confirmed TCP port `8102`, long-form power, volume,
mute and input queries, mute control, and input selection. It also confirmed
that direct two- and three-digit exact-volume commands are ignored by the
tested receiver firmware. A probe on 2026-11-25 showed that each `VU`/`VD`
changes the raw volume by exactly 2 (1 dB) and that the receiver refuses a
second simultaneous TCP connection.

</details>

## Development

```bash
pytest
ruff check .
python3 -m compileall custom_components scripts tests
```

The automated suite uses a local fake receiver and covers command encoding,
fragmented and unsolicited replies, malformed responses, timeouts, serialized
commands, reconnect behavior, state conversion, and single volume steps. Live
acceptance still requires guarded validation against a real VSX-827.

## Scope and limitations

- Pioneer VSX-827 main zone only.
- TCP/IP only; no serial configuration or adapter.
- No independent Speaker B / Zone 2 entity.
- No media playback controls.
- Volume changes in 1 dB steps; the slider raises by at most 10 dB per change.
- Only one control connection at a time (receiver limitation).
- No cloud service or remote-access relay.
- Listening-mode selection without current-mode feedback.
- Network power-on is impossible when the receiver disables its network
  interface; the entity can still remain available as `off`.

## License

Released under the [MIT License](LICENSE). You may use, modify, and distribute
the project while retaining its copyright and license notice. The software is
provided without warranty.
