# Pioneer AVR for Home Assistant

Local Home Assistant control for the Pioneer VSX-827 over its Ethernet
connection. The receiver is represented as a Home Assistant **AV receiver**: a
`media_player` entity whose device class is `receiver`.

This project has no cloud dependency. Version 0.1 supports the main zone only
and intentionally limits itself to the VSX-827 control families that can be
validated against Pioneer's 2012 protocol.

## VSX-827 control-interface research

The VSX-827 has Ethernet, AirPlay, DLNA, Internet Radio, and support for
Pioneer's ControlApp. Pioneer's product page lists the Ethernet connection and
ControlApp support:

- [Pioneer VSX-827 product information](https://www.pioneer-audiovisual.de/uk/node/408/)
- [Pioneer VSX-827/527 operating manual](https://www.homesound.ro/manuals/VSX-527-827.pdf)

The receiver accepts Pioneer's text command protocol over a TCP socket on port
`8102`. A VSX-827 owner report specifically confirms successful control on
8102; it also notes that an open ControlApp session can consume a receiver
connection:

- [VSX-827 port 8102 field report](https://homematic-forum.de/forum/viewtopic.php?f=31&start=30&t=12267)

Pioneer's 2012 external-command document describes its command list as common
to IP control and RS-232C. The open VSX-1022 command transcript provides the
power, volume, mute, input, and query forms used here:

- [2012 Pioneer IP and RS-232 command-document summary](https://www.scribd.com/document/621112255/Elite-Pioneer-Fy13avr-Ip-Rs-232-5-8-12-1)
- [VSX-1022 protocol transcript](https://github.com/schaffman5/VSX-1022_Commands/blob/master/Pioneer_VSX-1022_Commands_2012.txt)
- [Existing Home Assistant Pioneer integration](https://www.home-assistant.io/integrations/pioneer/)

The VSX-827 does **not** have a physical RS-232 connector. Its rear-panel
connections list Ethernet but no serial port. Consequently this integration
uses LAN/TCP directly and requires no USB or serial adapter. Although the
receiver has a Speaker B mode, it is not an independently powered, sourced,
and volume-controlled Zone 2, so this integration does not create a Zone 2
entity.

### Command status

| Function | TCP command | Reply | Status |
| --- | --- | --- | --- |
| Power on/off | `PO` / `PF` | `PWR0` / `PWR1` or `PWR2` | Implemented |
| Power query | `?PWR` | `PWRn` | Implemented |
| Volume up/down | `VU` / `VD` | `VOLnnn` update | Implemented |
| Exact volume | confirmed `VU`/`VD` sequence | `VOLnnn` after every step | Safely emulated |
| Volume query | `?VOL` | `VOLnnn` | Implemented |
| Mute on/off | `MO` / `MF` | `MUT0` / `MUT1` | Implemented |
| Mute query | `?MUT` | `MUTn` | Implemented |
| Select input | `nnFN` | `FNnn` | Implemented |
| Input query | `?FN` | `FNnn` | Implemented |
| Listening-mode groups | `0005SR`, `0010SR`, `0100SR` | generic `R` | Implemented without current-mode state |
| Independent Zone 2 | model dependent | model dependent | Not supported by VSX-827 hardware |

These commands are documented for the relevant 2012 Pioneer protocol family.
Run the guarded hardware validation below before treating every write command
as confirmed on an individual VSX-827 and firmware version.

Live VSX-827 tests confirmed TCP port `8102`, the long-form power, volume, mute,
and input queries, mute control, and input selection from Game to CD. The
receiver ignored both three-digit `nnnVL` and two-digit `nnVL` exact-volume
commands while continuing to report its old volume. The Home Assistant slider
is therefore implemented conservatively: it sends one `VU` or `VD`, waits for
the exact next `VOLnnn` state, and only then sends the next step. If any step is
not confirmed, the operation stops without retrying that non-idempotent command.
A later run also demonstrated that the receiver can
occasionally ignore a valid mute command. Idempotent mute, source, and volume
state operations are queried instead of being assumed successful. Mute and
source commands may be safely retried because setting the same target again
cannot overshoot it.

## Home Assistant features

- Power on and off
- Current volume display, single-step control, and safely emulated exact volume
- Mute and unmute
- Current input and input selection
- Immediate handling of unsolicited receiver updates plus a 30-second refresh
- Config flow, reconfiguration, device registry, availability, and sanitized
  diagnostics

The known input map includes CD, Tuner, DVD, TV, SAT/CBL, Video, DVR/BDR,
iPod/USB, BD, Adapter Port, Internet Radio, Pandora, Media Server, Favorites,
AirPlay, DMR, and Game. AirPlay and DMR can be reported as the current source
but are not offered for direct selection because the 2012 command notes state
that they cannot be selected with an `FN` command.

The receiver's ControlApp documentation and 2012 command list confirm three
listening-mode button groups. Home Assistant exposes **Auto / Direct**,
**Standard / ALC**, and **Advanced Surround**. Selecting one sends `0005SR`,
`0010SR`, or `0100SR` once. The VSX-827 returns only the generic `R` response to
all tested current-mode queries (`?S`, `?SR`, `?L`, and `?LM`), so the
integration intentionally does not claim a current sound-mode state. The
selected group may cycle among modes depending on the current source and audio
signal, matching Pioneer ControlApp behavior.

### Automatic discovery

The VSX-827 advertises itself as a UPnP MediaRenderer. Its device description
provides all data needed for precise SSDP discovery:

- manufacturer `PIONEER CORPORATION`
- model `VSX-827/SYXE8`
- `X_ipRemoteReady=1`
- `X_ipRemoteTcpPort=8102`
- a stable UPnP UUID

Home Assistant uses that model/manufacturer match to offer the discovered AVR
in **Settings → Devices & services**. The UUID becomes the stable config-entry
identity, and rediscovery can update a changed IP address.

## Receiver setup

1. Connect the VSX-827 to the same local network as Home Assistant using its
   Ethernet port.
2. Give it a stable DHCP reservation.
3. In the receiver's Network Setup menu, enable **Network Standby**. Without
   this setting the network interface may shut down with the main zone, making
   power-on over TCP impossible.
4. Close Pioneer ControlApp while testing. Older receivers permit only a small
   number of simultaneous control connections.

## Installation

### Manual

1. Copy `custom_components/pioneer_avr` into the `custom_components` directory
   inside your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**.
4. Search for **Pioneer AVR**.
5. Enter the receiver's hostname/IP and TCP port. The default is `8102`.

The setup flow opens a connection and requires a valid Pioneer power response
before creating the entry. YAML configuration is not supported.

### HACS custom repository

Until this repository is published in the HACS default store, add its GitHub
URL in HACS as a custom repository with category **Integration**, install
**Pioneer AVR**, restart Home Assistant, and then follow the UI setup above.

Repository URL:

```text
https://github.com/JoKeks2023/Pioneer-AVR-Homeassistant
```

## Debugging and hardware validation

The standalone tool imports the same asynchronous client as Home Assistant and
does not require Home Assistant itself.

Query basic state:

```bash
python3 scripts/debug_receiver.py 192.0.2.10 --query
```

Send a raw documented command and wait for a particular reply prefix:

```bash
python3 scripts/debug_receiver.py 192.0.2.10 --command '?PWR' --expect PWR
```

Run guarded state-changing validation:

```bash
python3 scripts/debug_receiver.py 192.0.2.10 --validate
```

The guarded test records the initial state, powers on if necessary, verifies
mute, leaves volume unchanged, checks a temporary input, and restores the
original power, mute, and selectable input in a `finally` block. Every tested
operation prints `PASS` only after a fresh state query confirms it, followed by
the final restored state. Keep
speakers and connected equipment in a safe state whenever testing receiver
control.

Enable debug logging in Home Assistant if needed:

```yaml
logger:
  logs:
    custom_components.pioneer_avr: debug
```

Logs record response prefixes and connection failures, not the configured host
or raw receiver payload. Downloadable diagnostics redact the host.

## Development

Install the test tools in a virtual environment, then run:

```bash
pytest
ruff check .
python3 -m compileall custom_components scripts tests
```

The network tests use a local fake receiver and cover fragmented replies,
unsolicited updates, state parsing, and serialized commands. Live acceptance
still requires `scripts/debug_receiver.py --validate` against the target
VSX-827.

## Current limitations

- VSX-827 main zone only; Speaker B is not exposed as Zone 2.
- TCP/IP only; the receiver has no RS-232 socket and needs no adapter.
- Listening-mode selection has no current-state feedback because the VSX-827
  returns only `R` to all documented mode queries.
- No cloud features or remote access outside the local network.
