---
title: JSON API
hide:
  # - navigation
  # - toc
---

WLED versions since 0.8.4 implement a powerful JSON API over HTTP.  
It is accessible using the `/json` subpage.

### Obtaining light information

Sending a GET request will return an object similar to the sample below
The response consists of four objects:

- `state` contains the current state of the light. All values may be modified by the client (see below)
- `info` contains general information about the device. No value can be modified using this API
- `effects` contains an array of the effect mode names
- `palettes` contains an array of the palette names

You may also obtain those objects individually using the URLs `/json/state` `/json/info` `/json/eff`, and `/json/pal`.

!!! info "Reserved effect IDs"
    In WLED versions 0.14+, some effects are unsupported in certain builds (e.g. some audio reactive effects may only work on ESP32).
    In order for each effect to have an unique ID on all devices, having unsupported ones in between supported ones is possible.
    If called, these will fallback to the Solid effect, in the effects list they have the name `RSVD` or `-`.
    To improve user experience, it is recommended to remove effects with the names `RSVD` or `-` form the UI effect selection.

### Client libraries

The community has created libraries for various programming languages to make working with the WLED JSON API easier.

- [WLED JSON API Library in Rust](https://github.com/paulwrath1223/wled-json-api-library) - Even if you are not using Rust, or don't know how to read Rust, the up-to-date JSON structure is included and documented in this project.
- [python-wled](https://github.com/frenck/python-wled) - Python library for the WLED JSON API and the WLED Weboscket API.

### Setting new values

Sending a POST request to `/json` or `/json/state` with (parts of) the state object will update the respective values.
Example: `{"on":true,"bri":255}` sets the brightness to maximum. `{"seg":[{"col":[[0,255,200]]}]}` sets the color of the first segment to teal.
`{"seg":[{"id":X,"on":"t"}]}` and replacing X with the desired segment ID will toggle on or off that segment.

!!! tldr "CURL example"
    This will toggle on and off and return the new state (v0.13+):
    `curl -X POST "http://[WLED-IP]/json/state" -d '{"on":"t","v":true}' -H "Content-Type: application/json"`

Sample JSON API response (v0.8.4):

```json
{
  "state": {
    "on": true,
    "bri": 127,
    "transition": 7,
    "ps": -1,
    "pl": -1,
    "nl": {
      "on": false,
      "dur": 60,
      "fade": true,
      "tbri": 0
    },
    "udpn": {
      "send": false,
      "recv": true
    },
    "seg": [{
      "start": 0,
      "stop": 20,
      "len": 20,
      "col": [
        [255, 160, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0]
      ],
      "fx": 0,
      "sx": 127,
      "ix": 127,
      "pal": 0,
      "sel": true,
      "rev": false,
      "cln": -1
    }]
  },
  "info": {
    "ver": "0.8.4",
    "vid": 1903252,
    "leds": {
      "count": 20,
      "rgbw": true,
      "pin": [2],
      "pwr": 0,
      "maxpwr": 65000,
      "maxseg": 1
    },
    "name": "WLED Light",
    "udpport": 21324,
    "live": false,
    "fxcount": 80,
    "palcount": 47,
    "arch": "esp8266",
    "core": "2_4_2",
    "freeheap": 13264,
    "uptime": 17985,
    "opt": 127,
    "brand": "WLED",
    "product": "DIY light",
    "btype": "src",
    "mac": "60019423b441"
  },
  "effects": [
    "Solid", "Blink", "Breathe", "Wipe", "Wipe Random", "Random Colors", "Sweep", "Dynamic", "Colorloop", "Rainbow",
    "Scan", "Dual Scan", "Fade", "Chase", "Chase Rainbow", "Running", "Saw", "Twinkle", "Dissolve", "Dissolve Rnd",
    "Sparkle", "Dark Sparkle", "Sparkle+", "Strobe", "Strobe Rainbow", "Mega Strobe", "Blink Rainbow", "Android", "Chase", "Chase Random",
    "Chase Rainbow", "Chase Flash", "Chase Flash Rnd", "Rainbow Runner", "Colorful", "Traffic Light", "Sweep Random", "Running 2", "Red & Blue","Stream",
    "Scanner", "Lighthouse", "Fireworks", "Rain", "Merry Christmas", "Fire Flicker", "Gradient", "Loading", "In Out", "In In",
    "Out Out", "Out In", "Circus", "Halloween", "Tri Chase", "Tri Wipe", "Tri Fade", "Lightning", "ICU", "Multi Comet",
    "Dual Scanner", "Stream 2", "Oscillate", "Pride 2015", "Juggle", "Palette", "Fire 2012", "Colorwaves", "BPM", "Fill Noise", "Noise 1",
    "Noise 2", "Noise 3", "Noise 4", "Colortwinkle", "Lake", "Meteor", "Smooth Meteor", "Railway", "Ripple"
  ],
  "palettes": [
    "Default", "Random Cycle", "Primary Color", "Based on Primary", "Set Colors", "Based on Set", "Party", "Cloud", "Lava", "Ocean",
    "Forest", "Rainbow", "Rainbow Bands", "Sunset", "Rivendell", "Breeze", "Red & Blue", "Yellowout", "Analogous", "Splash",
    "Pastel", "Sunset 2", "Beech", "Vintage", "Departure", "Landscape", "Beach", "Sherbet", "Hult", "Hult 64",
    "Drywet", "Jul", "Grintage", "Rewhi", "Tertiary", "Fire", "Icefire", "Cyane", "Light Pink", "Autumn",
    "Magenta", "Magred", "Yelmag", "Yelblu", "Orange & Teal", "Tiamat", "April Night"
  ]
}
```

### Overview of values

#### State object

| JSON key | Value range | Description
| --- | --- | --- |
on | bool | On/Off state of the light. You can also use `"t"` instead of `true` or `false` to toggle.
<a id="bri"></a> bri | 0 to 255 | Brightness of the light. If _on_ is `false`, contains last brightness when light was on (aka brightness when _on_ is set to true). Setting _bri_ to 0 is supported but it is recommended to use the range 1-255 and use `on: false` to turn off. The state response will never have the value `0` for _bri_.
transition | 0 to 65535 | Duration of the crossfade between different colors/brightness levels. One unit is 100ms, so a value of `4` results in atransition of 400ms.
tt | 0 to 65535 | Similar to transition, but applies to just the current API call. Not included in state response.
ps | -1 to 250 | ID of currently set preset. `1~17~` can be used to iterate through presets 1-17, or `4~10r` to select random preset between presets 4 and 10 (inclusive).
~~pss~~ | 0 to 65535 | Bitwise indication of preset slots (0 - vacant, 1 - written). Always 0 in 0.11. Not changable. _Removed as of v0.11.1_
psave | 1 to 250 (16 prior to 0.11) | Save current light config (state) to specified preset slot. Not included in state response.
sb | bool | Used with `psave`. Save segment bounds (`start` & `stop`).
ib | bool | Used with `psave`. Save [brightness](#bri).
sc | bool | Used with `psave`. Save [selected segments](#seg-sel).
pl | -1 to 250 | ID of currently set playlist. _(read-olny)_
pdel | 1 to 250 | Preset ID to delete. Not included in state response.
nl.on | bool | Nightlight currently active
nl.dur | 1 to 255 | Duration of nightlight in minutes
~~nl.fade~~ | bool | If `true`, the light will gradually dim over the course of the nightlight duration. If `false`, it will instantly turn to the target brightness once the duration has elapsed. _Removed in 0.13.0_ (use mode instead)
nl.mode | 0 to 3 | Nightlight mode (0: instant, 1: fade, 2: color fade, 3: sunrise) (available since 0.10.2)
nl.tbri | 0 to 255 | Target brightness of nightlight feature
nl.rem | -1 to 15300 | Remaining nightlight duration in seconds, -1 if not active. Only in state response, can not be set.
udpn.send | bool | Send WLED broadcast (UDP sync) packet on state change
udpn.recv | bool | Receive broadcast packets
udpn.sgrp | 0 to 255 | Bitfield for broadcast send groups 1-8
udpn.rgrp | 0 to 255 | Bitfield for broadcast receive groups 1-8
udpn.nn | bool | Don't send a broadcast packet (applies to just the current API call). Not included in state response.
v | bool | If set to _true_ in a JSON POST command, the response will contain the full JSON state object. Not included in state response
rb | bool | If set to _true_, device will reboot immediately. Not included in state response.
live | bool | If set to _true_, enters realtime mode and blanks the LEDs. The realtime timeout option does not have an effect when this command is used, WLED will stay in realtime mode until the state (color/effect/segments, excluding brightness) is changed. It is expected that `{"live":false}` is sent once live data sending is terminated. Not included in state response.
lor | 0, 1, or 2 | Live data override. 0 is off, 1 is override until live data ends, 2 is override until ESP reboot (available since 0.10.0)
time | uint32 | Set module time to unix timestamp. Not included in state response.
mainseg | 0 to info.leds.maxseg-1 | Main Segment | Sets which segment ID is the main segment. The main segment's values are the ones sent by UDP sync, and in case no segment is selected, all changes done via the `"seg":{}` syntax without a segment `id` specified are applied to the main segment. If the main segment is deleted, the first active segment becomes the new main segment.
seg | Object or Array of objects | _(see below)_ Segments are individual parts of the LED strip. Since 0.9.0 this enables running different effects on differentparts of the strip.
playlist | object | [Custom preset playlists](#playlists). Not included in state response. _(available since 0.11.0)_
tb | uint32 | Sets timebase for effects. Not reported.
ledmap | 0 to 9 | Load specified ledmap (0 for `ledmap.json`, 1-9 for `ledmap1.json` to `ledmap9.json`). [See mapping](/advanced/mapping/). Not included in state response. _(available since 0.14.0)_
rmcpal | bool | Remove last custom palette if set to `true`. Not included in state response. _(available since 0.14.0)_
np | bool | Advance to the next preset in a playlist if set to `true`. Not included in state response. _(available since 0.15)_

#### Contents of the segment object

!!! info "Legacy limitation (v0.8.4)"
    _start_, _stop_, and _len_ are not changeable in v0.8.4. Any segment with _id_ > 0 is ignored.  
    Unless stated otherwise, every value may be changed via an HTTP POST request.  
    The tertiary color is not gamma-corrected in 0.8.4, but is in subsequent releases.

| JSON key | Value range | Description
| --- | --- | --- |
id | 0 to info.maxseg -1 | Zero-indexed ID of the segment. May be omitted, in that case the ID will be inferred from the order of the segment objects in the _seg_ array.
start | 0 to info.leds.count -1 | LED the segment starts at. For 2D set-up it determines column where segment starts, from top-left corner of the matrix.
stop | 0 to info.leds.count | LED the segment stops at, not included in range. If _stop_ is set to a lower or equal value than _start_ (setting to `0` is recommended), the segment is invalidated and deleted. For 2D set-up it determines column where segment stops, from top-left corner of the matrix.
startY | 0 to matrix width | Start row from top-left corner of a matrix. _(available since 0.14.0)_
stopY | 1 to matrix height | Stop row from top-left corner of matrix. _(available since 0.14.0)_
len | 0 to info.leds.count | Length of the segment (_stop_ - _start_). _stop_ has preference, so if it is included, _len_ is ignored.
grp | 0 to 255 | Grouping (how many consecutive LEDs of the same segment will be grouped to the same color)
spc | 0 to 255 | Spacing (how many LEDs are turned off and skipped between each group)
of | -len+1 to len | Offset (how many LEDs to rotate the virtual start of the segments, available since 0.13.0)
col | array of colors | Array that has up to 3 color arrays as elements, the primary, secondary (background) and tertiary colors of the segment. Each color is an array of 3 or 4 bytes, which represents an RGB(W) color, i.e. `[[255,170,0],[0,0,0],[64,64,64]]`. It can also be represented as an array of strings of _hex_ values, i.e. `["FFAA00","000000","404040"]` for orange, black and grey. One or more colors can be set randomly with `"r"`, i.e. `["r",[0,0,0],"r"]`. _(random available since 16.0.0)_
fx | 0 to info.fxcount -1 | ID of the effect or `~` to increment, `~-` to decrement, or `"r"` for random.
sx | 0 to 255 | Relative effect speed. `~` to increment, `~-` to decrement. `~10` to increment by 10, `~-10` to decrement by 10.
ix | 0 to 255 | Effect intensity. `~` to increment, `~-` to decrement. `~10` to increment by 10, `~-10` to decrement by 10.
c1 | 0 to 255 | Effect custom slider 1. Custom sliders are hidden or displayed and labeled based on [effect metadata](#effect-metadata).
c2 | 0 to 255 | Effect custom slider 2.
c3 | 0 to 31 | Effect custom slider 3.
o1 | bool | Effect option 1. Custom options are hidden or displayed and labeled based on [effect metadata](#effect-metadata).
o2 | bool | Effect option 2.
o3 | bool | Effect option 3.
pal | 0 to info.palcount -1 | ID of the color palette or ~ to increment, ~- to decrement, or r for random.
<a id="seg-sel"></a>sel | bool | `true` if the segment is selected. Selected segments will have their state (color/FX) updated by APIs that don't support segments (e.g. UDP sync, HTTP API). If no segment is selected, the first segment (_id_:`0`) will behave as if selected. WLED will report the state of the first (lowest _id_) segment that is selected to APIs (HTTP, MQTT...), or `mainseg` in case no segment is selected and for the UDP API. Live data is always applied to all LEDs regardless of segment configuration.
rev | bool | Flips the segment (in horizontal dimension for 2D set-up), causing animations to change direction.
rY | bool | Flips the 2D segment in vertical dimension. _(available since 0.14.0)_
on | bool | Turns on and off the individual segment. _(available since 0.10.0)_
bri | 0 to 255 | Sets the individual segment brightness _(available since 0.10.0)_
mi | bool | Mirrors the segment (in horizontal dimension for 2D set-up) _(available since 0.10.2)_
mY | bool | Mirrors the 2D segment in vertical dimension. _(available since 0.14.0)_
tp | bool | Transposes a segment (swaps X and Y dimensions). _(available since 0.14.0)_
cct | 0 to 255 _or_ 1900 to 10091 | White spectrum [color temperature](#cct-control) _(available since 0.13.0)_
lx | `BBBGGGRRR`: 0 - 100100100 | Loxone RGB value for primary color. Each color (`RRR`,`GGG`,`BBB`) is specified in the range from 0 to 100%. _Only available if Loxone is compiled in._
lx | `20bbbtttt`: 200002700 - 201006500 | Loxone brightness and color temperature values for primary color. Brightness `bbb` is specified in the range 0 to 100%. `tttt` defines the color temperature in the range from 2700 to 6500 Kelvin. (available since 0.11.0, not included in state response) _Only available if Loxone is compiled in._
ly | `BBBGGGRRR`: 0 - 100100100 | Loxone RGB value for secondary color. Each color (`RRR`,`GGG`,`BBB`) is specified in the range from 0 to 100%. _Only available if Loxone is compiled in._
ly | `20bbbtttt`: 200002700 - 201006500 | Loxone brightness and color temperature values for secondary color. Brightness `bbb` is specified in the range 0 to 100%. `tttt` defines the color temperature in the range from 2700 to 6500 Kelvin. _(available since 0.11.0, not included in state response)_ _Only available if Loxone is compiled in._
i | array | [Individual LED control](#per-segment-individual-led-control). Not included in state response _(available since 0.10.2)_
frz | bool | freezes/unfreezes the current effect
m12 | 0 to 4 [map1D2D.count] | Setting of segment field 'Expand 1D FX'. (0: Pixels, 1: Bar, 2: Arc, 3: Corner)
si | 0 to 3 | Setting of the sound simulation type for audio enhanced effects. (0: 'BeatSin', 1: 'WeWillRockYou', 2: '10_3', 3: '14_3') (_as of 0.14.0-b1, there are these 4 types defined_)
fxdef | bool | Forces loading of effect defaults (speed, intensity, etc) from effect [metadata](#effect-metadata). _(available since 0.14.0)_
set | 0 to 3 | Assigns group or set ID  to segment (not to be confused with *grouping*). Visual aid only (helps in UI). _(available since 0.14.0)_
rpt | bool | Flag to repeat current segment settings by creating segments until all available LEDs are included in automatically created segments or maximum segments reached. Will also toggle *reverse* on every *even* segment. _(available since 0.13.0)_

#### Info object

No value may be changed by means of this API.

| JSON key | Value range | Description
| --- | --- | --- |
ver | string | Version name.
vid | uint32 | Build ID (YYMMDDB, B = daily build index).
_leds_ | object | Contains info about the LED setup.
leds.cct | bool | `true` if the light supports [color temperature control](#cct-control) _(available since 0.13.0, deprecated, use info.leds.lc)_
leds.count | 1 to 1200 | Total LED count.
leds.fps | 0 to 255 | Current frames per second. _(available since 0.12.0)_
leds.rgbw | bool | `true` if LEDs are 4-channel (RGB + White). _(deprecated, use info.leds.lc)_
leds.wv | bool | `true` if a white channel slider should be displayed. _(available since 0.10.0, deprecated, use info.leds.lc)_
~~leds.pin~~ | byte array | LED strip pin(s). Always one element. _Removed as of v0.13_
leds.pwr | 0 to 65000 | Current LED power usage in milliamps as determined by the ABL. `0` if ABL is disabled.
leds.maxpwr | 0 to 65000 | Maximum power budget in milliamps for the ABL. `0` if ABL is disabled.
leds.maxseg | byte | Maximum number of segments supported by this version.
leds.lc | byte | Logical AND of all active segment's virtual light capabilities
leds.seglc | byte array | Per-segment virtual light capabilities
str | bool | If `true`, an UI with only a single button for toggling sync should toggle receive+send, otherwise send only
name | string | Friendly name of the light. Intended for display in lists and titles.
udpport | uint16 | The UDP port for realtime packets and WLED broadcast.
live | bool | If `true`, the software is currently receiving realtime data via UDP or E1.31.
lm | string | Info about the realtime data source
lip | string | Realtime data source IP address
ws | -1 to 8 | Number of currently connected WebSockets clients. -1 indicates that WS is unsupported in this build.
fxcount | byte | Number of effects included.
palcount | uint16 | Number of palettes configured.
_wifi_ | object | Info about current signal strength
wifi.bssid | string | The BSSID of the currently connected network.
wifi.signal | 0 to 100 | Relative signal quality of the current connection.
wifi.channel | 1 to 14 | The current WiFi channel.
_fs_ | object | Info about the embedded LittleFS filesystem (since 0.11.0)
fs.u | uint32 | Estimate of used filesystem space in kilobytes
fs.t | uint32 | Total filesystem size in kilobytes
fs.pmt | uint32 | Unix timestamp for the last modification to the `presets.json` file. Not accurate after boot or after using `/edit`
ndc | -1 to 255 | Number of other WLED devices discovered on the network. -1 if Node discovery disabled. (since 0.12.0)
arch | string | Name of the platform.
core | string | Version of the underlying (Arduino core) SDK.
lwip | 0, 1, or 2 | Version of LwIP. 1 or 2 on ESP8266, 0 (does not apply) on ESP32. _Deprecated, removal in 0.14.0_
freeheap | uint32 | Bytes of heap memory (RAM) currently available. Problematic if <`10k`.
uptime | uint32 | Time since the last boot/reset in seconds.
opt | uint16 | Used for debugging purposes only.
brand | string | The producer/vendor of the light. Always `WLED` for standard installations.
product | string | The product name. Always `FOSS` for standard installations.
~~btype~~ | string | The origin of the build. `src` if a release version is compiled from source, `bin` for an official release image, `dev` for a development build (regardless of src/bin origin) and `exp` for experimental versions. `ogn` if the image is flashed to hardware by the vendor. _Removed as of v0.10_
mac | string | The hexadecimal hardware MAC address of the light, lowercase and without colons.
ip | string | The IP address of this instance. Empty string if not connected. (since 0.13.0)
device_id | string | A unique identifier for the device, derived from the hardware MAC address. _(available since 16.0.0)_
psram | uint32 | Total PSRAM size in bytes. `0` if no PSRAM is present or detected. _(available since 16.0.0)_
psram_free | uint32 | Estimate of currently free PSRAM in bytes. _(available since 16.0.0)_
repo | string | URL of the source code repository for this firmware build. _(available since 16.0.0)_

Examples of frequently requested custom API:

| Function/Effect | API (Add to preset or call from other sources)
| --- | --- |
Cycle presets between 1 and 6 | `{"ps":"1~6~"}`
Select random effect on _all selected_ segments | `{"seg":{"fx":"r"}}`
Select random palette between 5 and 10 on segment 2 | `{"seg":[{"id":2,"pal":"5~10r"}]}`
Change segment 0 name | `{"seg":[{"id":0,"n":"Your custom ASCII text"}]}`
Freeze or unfreeze an effect | `{"seg":[{"id":0,"frz":true}]}` or `{"seg":[{"id":0,"frz":false}]}`
Night light | `{"nl":{"on":true,"dur":10,"mode":0}}`
Increase brightness by 40 wrapping when maximum reached | `{"bri":"w~40"}`

#### Per-segment individual LED control

Using the `i` property of the segment object, you can set the LED colors in the segment using the JSON API.  
Keep in mind that this is non-persistent, if the light is turned off the segment will return to effect mode.  
The segment is frozen when using individual control, the set effect will not run.   
To unfreeze the segment, click the "eye" icon, change any property of the segment or turn off the light.

To set individual LEDs starting from the beginning, use an array of Color arrays `[255,0,0]` or hex values `"FF0000"`.
Hex values are more efficient than Color arrays and should be preferred when setting a large number of colors.  
`{"seg":{"i":["FF0000","00FF00","0000FF"]}}` or `{"seg":{"i":[[255,0,0],[0,255,0],[0,0,255]]}}` will set the first LED red, the second green and the third blue.

To set individual LEDs, use the LED index followed by its color value.  
`{"seg":{"i":[0,"FF0000",2,"00FF00",4,"0000FF"]}}` is the same as above, but leaves blank spaces between the lit LEDs.

To set ranges of LEDs, use the LED start and stop index followed by its color value.  
`{"seg":{"i":[0,8,"FF0000",10,18,"0000FF"]}}` sets the first eight LEDs to red, leaves out two, and sets another 8 to blue.

To set a large number of colors, send multiple api calls of 256 colors at a time.  
`{"seg": {"i":[0,"CC0000","00CC00","0000CC","CC0000"...]}}` 
`{"seg": {"i":[256,"CC0000","00CC00","0000CC","CC0000"...]}}`
`{"seg": {"i":[512,"CC0000","00CC00","0000CC","CC0000"...]}}`

Do not make several calls in parallel, that is not optimal for the device. Instead make your call in sequence, where each call waits for the previous to complete before making a new one. How this is done depends on your choice of tool, but with CURL you que your commands by separating then with ` && ` i.e. `CURL [command 1] && CURL [command 2] && CURL [command 3]`.

!!! tip "Command buffer size"
    If you are trying to set many LEDs and it fails to work, you can check your request [here](https://arduinojson.org/v6/assistant) for length.
    Select ESP32 and Deserialize. If the required buffer size is above 10K for ESP8266 and 24K for ESP32, please split it into multiple sequential requests and consider using the Hex string syntax.

Keep in mind that the LED indices are segment-based, so LED 0 is the first LED of the segment, not of the entire strip.
Segment features, including Grouping, Spacing, Mirroring and Reverse are functional.

Matrices are handled as a non-serpentine layout.

!!! info "Brightness interaction"
    For your colors to apply correctly, make sure the desired brightness is set beforehand. Turning on the LEDs from an off state and setting individual LEDs in the same JSON request will _not_ work!

#### Playlists

(Available since 0.11.0)

Sample playlist API call:

```json
{
  "playlist": {
    "ps": [26, 20, 18, 20],
    "dur": [30, 20, 10, 50],
    "transition": 0,
    "repeat": 10,
    "end": 21
  }
}
```

This example applies preset ID 26 for 3 seconds, then preset 20 for 2 seconds, then preset 18 for 1 second, lastly preset 20 again for 5 seconds.This repeats 10 times, then preset 21 is applied.

Playlist object:

| JSON key | Description
| --- | --- |
ps | Array of preset ID integers to be applied in this order.
dur | Array of time each preset should be kept, in tenths of seconds. If only one integer is supplied, all presets will be kept for that time.Defaults to 10 seconds if not provided.
transition | Array of time each preset should transition to the next one, in tenths of seconds. If only one integer is supplied, all presets will transition for that time. Defaults to the current transition time if not provided.
repeat | How many times the entire playlist should cycle before finishing. Set to `0` for an indefinite cycle. Default to indefinite if not provided.
end | Single preset ID to apply after the playlist finished. Has no effect when an indefinite cycle is set. If not provided, the light will stay on the last preset of the playlist.

#### Light capabilities

In order to e.g. only show color controls relevant to a given setup, it is necessary to obtain the color capabilities of the light.  
The `info.leds.seglc` array can be used to do so on a per-segment level. It contains `n+1` 8-bit integers, where `n` is the `id` of the last _active_ segment,
each index corresponds to the segment with that ID.  
This integer indicates whether a given segment supports (24 bit) RGB colors, an extra (8 bit) white channel and/or adjustable color temperature (CCT):  

| Bit | Capability
| --- | --- |
0 | Segment supports RGB color
1 | Segment supports white channel
2 | Segment supports color temperature
3-7 | Reserved (expect any value)

Therefore:  

| `lc` value | Capabilities
| --- | --- |
0 | None. Indicates a segment that does not have a bus within its range, e.g. because it is not active.
1 | Supports RGB
2 | Supports white channel only
3 | Supports RGBW
4 | Supports CCT only, no white channel (unused)
5 | Supports CCT + RGB, no white channel (unused)
6 | Supports CCT (including white channel) 
7 | Supports CCT (including white channel) + RGB

Note that CCT is controllable per-segment, while RGB color and white channel have 3 color slots each per segment.  
  
`info.leds.lc` contains this info on a global level, and is a bitwise AND of the per-segment light capability values.  

#### CCT control

Please also see the [general info about CCT](/features/cct).
##### Supported value ranges

Given that the white spectrum handling is agnostic to the true color temperature of the LEDs used, a relative range is preferred for the time being, where a value of `0` indicates the warmest possible color temperature, while a value of `255` indicates the coldest temperature.

It is also possible to pass a value in the range of `1900` to `10091`, in which case it is treated as a Kelvin color temperature, where `1900` is mapped to a relative value of `0` and `10091` to a relative value of `255`.

As such, it is unlikely to match the _actual_ color temperature output by the light, therefore the relative values 0-255 are preferred for the time being.

In the future, an option to specify the Kelvin temperatures of the utilized hardware may be added, once this is done, a color temperature can be set to more accurately match other lights.

Therefore, for forward compatibility, your integration should expect both either a 0-255 value for `seg.cct`, in which case it is a relative value, or an absolute Kelvin value in the range 1000-16000 K. In case a Kelvin value is provided, you can consider the color temperature as accurate, which is not possible with relative 0-255 values as the Kelvin points of the white channels are unknown.  
It is preferred that you set a new CCT value in the same range as received from WLED, that is, use 0-255 if the original value was within this range, and 1000-20000 K otherwise.

If your code relies on absolute Kelvin values, a reasonable estimate for the warm white point (relative `0`) could be 2700K, while cold white (relative `255`) could commonly be 6500K.

##### Effect of the seg.cct value

`seg.cct` can always be set, but only has an effect on the physical state of the light if one or both of the following conditions is met:

- White Balance correction is enabled
- A bus supporting CCT is configured and `Calculate CCT from RGB` is _not_ enabled

CCT support is indicated by `info.leds.cct` being `true`, in which case you can regard the instance as a CCT light and e.g. display a color temperature control.

#### Effect metadata

!!! tip "Why effect metadata?"
    Prior to 0.14, user interfaces showed Speed and Intensity slider, palette controls, and all three color slots regardless of the effect selected.
    This may cause confusion to the user because controls are displayed that have no immediate effect in the current configuration.
    Effect metadata allows you to dynamically hide certain controls, so that the user only sees controls actually utilized by the selected effect mode.

Starting with WLED 0.14, effect metadata is available under the `/json/fxdata` URL.  
This returns an array of strings with `info.fxcount` entries.
The string at a given index corresponds to the metadata of the effect with the same ID as that index.
Metadata is stored in a memory-optimized string format, for example the Aurora effect has the metadata `!,!;;!;1;sx=24,pal=50`.

The metadata string consists of up to five sections, separated by semicolons:
`<Effect parameters>;<Colors>;<Palette>;<Flags>;<Defaults>`

##### Effect parameters

The first section specifies the number and labels of effect parameters (e.g. speed, intensity).
Up to 5 sliders and 3 checkboxes are supported (`sx`,`ix`,`c1`,`c2`,`c3`,`o1`,`o2`,`o3` parameters in the `seg` object). For more details about the ranges of the sliders see [contents-of-the-segment-object](#contents-of-the-segment-object).
Slider/checkbox labels are comma separated.
An empty or missing label disables this control.
`!` specifies the default label is used:

| Parameter | Default tooltip label
| --- | --- |
sx | Effect speed
ix | Effect intensity
c1 | Custom 1
c2 | Custom 2
c3 | Custom 3
o1 | Option 1
o2 | Option 2
o3 | Option 3

The fallback value if this section is missing is two sliders, Effect speed and Effect intensity.

Examples:  

| Parameter string | Displayed controls
| --- | --- |
`<empty>` | No effect parameters
! | 1 slider: Effect speed
!,! | 2 sliders: Effect speed + Effect intensity
!,Phase | 2 sliders: Effect speed + Phase
,Saturation,,,,Invert | 1 slider (sets `ix` parameter) and 1 checkbox: Saturation + Invert
,,,,,Random colors | 1 checkbox: Random colors

##### Colors

Up to 3 colors can be used. Please note that only the first two characters of the label are visible in the WLED UI.  
`!` specifies the default label is used. The default labels for the color slots are `Fx`, `Bg`, and `Cs`.

The fallback value if this section is missing is 3 colors: `Fx` + `Bg` + `Cs`.

Examples:  

| Colors string | Displayed controls
| --- | --- |
`<empty>` | No color controls
! | 1 color: Fx
,! | 1 color: Bg
!,! | 2 colors: Fx + Bg
1,2,3 | 3 colors: 1 + 2 + 3

##### Palette

If empty, the effect does not use palettes. If `!`, palette selection is enabled.

The fallback value if this section is missing is palette selection enabled.

##### Flags

Flags allow filtering for effects with certain characteristics.
They are a single character each and not comma-separated.
Currently, the following flags are specified:

| Flag | Effect characteristic
| --- | --- |
0 | Effect works well on a single LED. If flag 0 is present, flags 1/2/3 are omitted. (unused)
1 | Effect is optimized for use on 1D LED strips.
2 | Effect requires a 2D matrix setup (unless flag 1 is also present)
3 | Effect requires a 3D cube (unless flags 1 and/or 2 are also present) (unused)
v | Effect is audio reactive, reacts to amplitude/volume.
f | Effect is audio reactive, reacts to audio frequency distribution.

For example, a Flag string of `2v` denotes a volume reactive effect that is to be used on 2D matrices.

The fallback value if this section is missing is `1`, i.e. a 1D optimized effect.

##### Defaults

Defaults are values for effect parameters that work particularly well on that effect.
They are set automatically when the effect is selected in UI unless configured otherwis in UI settings.
To specify defaults, use the standard segment parameter name (e.g. `ix`) followed by an `=` and the default value.
For example, `sx=24,pal=50` sets the effect speed to 24 (slow) and the palette to ID 50 (Aurora).

If no default is specified for a given parameter, it retains the current value.

### Sensors

!!! warning
    This section about the Sensor API is a DRAFT specification. It is not yet implemented and subject to change.

Various types of sensors (e.g. for Temperature, light intensity, PIR) may be added to WLED via usermods.
To allow read access to sensor data via the JSON API in a standardized way, the `info.sensor` array is used.

If the `info.sensor` array is missing or empty, no sensor values are exposed.

#### Sensor object

Each sensor/measurement is represented by an object within the `info.sensor` array.

For example,

```json
{"type":"T","n":"Outside","val":12}
```

refers to a 12 °C temperature measurement in Celsius with the sensor name "Outside".

The object may contain the following properties, of which all are optional, except `type`.

| JSON key | Value range | Description
| --- | --- | --- |
type | string | The type of the sensor.
n | string | The name of the sensor. If omitted, the client may generate a suitable name (e.g. "Temperature sensor 1") 
val | any | The most current sensor reading. May be of any JSON type depending on the type of the sensor, this is a number for all sensor types pre-defined below except for the `"b"` and `"CL"` types and custom type sensors. `null` if the reading is invalid, either due to an error or because the first reading has not yet completed.
unit | string | An explicit human-readable unit string for the measurement. If omitted, the default for the sensor type is used.
error | int or string | If present and not `null`,`false`,`0` or an empty string, a sensor error is indicated. May either be an integer error code or an error string.
tc | number | Seconds of WLED `uptime` when the value last changed substantially. The threshold for a "substantial" change is up to the implementation. This can for example be used to find when a PIR sensor was last activated. 
tm | number | Seconds of WLED `uptime` when the last reading given by `val` was obtained.
ts | number | Seconds of WLED `uptime` at the first measurement / start of measurement period. (required for Energy sensor type)
min | number | Lower bound of possible value range
max | number | Upper bound of possible value range
u | number | Absolute uncertainty of the measurement
model | string | Identification of the sensor hardware used

#### Sensor types

These are the standardized sensor types that may be implemented by usermods:

| Type ID string | Measurement type | Default unit
| --- | --- | --- |
"" (empty string) | Invalid sensor (reserved) | - 
b | Button/Boolean | true/false
c | Custom user-defined sensor | -
q | Electric charge | As
t | Time | s
BL| Battery Level | %
CL| 24-bit RGB color | hex string
E | Energy (`ts` property required) | J
I | Electric current | A
J | Illuminance | lx
L | Distance | m
Lp| Sound pressure level | dB
M | Mass | kg
N | Number/count | -
P | Power | W
Pe| General purpose percentage | %
PL| Power Level (signal strength) | dBm
Pr| Pressure | Pa
R | Electric Resistance | Ohms
RH| Relative Humidity | %
T | Temperature | °C
U | Voltage | V
(other strings) | Reserved, let us know if you need a new type added | -

If a client is only interested in certain sensor types (e.g. Temperature), it may disregard all other sensor objects.

### API
there is all routes for JSON API:

- /json/state
- /json/info
- /json/si
- /json/nodes
- /json/eff
- /json/palx
- /json/fxdata
- /json/net
- /json/live // only if flag WLED_ENABLE_JSONLIVE is on
- /json/pal
- /json/cfg


---
title: White handling
hide:
  # - navigation
  # - toc
---

### White channel(s) handling

Besides addressable RGB and RGBW bus types, WLED 0.13.0 also supports PWM CCT (correlated color temperature) lights.

#### Auto white handling

Many effects and realtime sources are based on an RGB color model, which necessitates a method to calculate a white channel value from the RGB value for lights that support more than RGB.

WLED offers four auto white modes, one of which can be selected in LED settings using the option `Auto-calculate white channel from RGB`. This option is only shown if at least one bus with White channel support is present.

| Auto White mode | Description |
|---|---|
Accurate | This mode subtracts the calculated white value from the RGB channels. This gets rid of the "RGB-white" but means that the light is less bright with only the white channel and not the RGB channels being utilized for pure white.
Brighter | This does the exact opposite and not touch the RGB channels at all, just mix in the dedicated white.
None | No auto white calculation is performed. The white channel of colors can be manually set using the `White channel` slider in the user interface, RGB-only effects and most realtime sources will leave the white channel off.
Dual | The `White channel` slider is present in the UI and works the same as in `None` mode, however if the slider value is 0 (far left), the `Brighter` mode is used for auto white calculation. This is the default auto white mode.
Max | Sets white to the value of the brightest RGB channel. This is good for white-only LEDs without any RGB.
  
If you set the mode to anything other than 'None', the LEDs will be treated internally like having RGB channels (you'll see the colour picker in the UI).  
`Accurate` and `Brighter` methods are applied on a per-pixel basis, so they also work in color palettes and realtime effects!  

#### White Balance correction

If enabled in LED settings, WB correction allows either making all pixels colder or warmer on a per-segment basis using a slider in the main user interface.  
This is applied to the RGB color only, after the auto white channel calculation.

#### CCT handling

WLED starting with version 0.13.0 also supports bus types with two white channels, one with a warm color temperature (e.g. 2700 Kelvin, reddish white) and one with a cold white color temperature (e.g. 8000 Kelvin, bluish white).

Since as of the release of version 0.13.0 no adjustable CCT addressable LEDs are supported*, this only applies to PWM analog LED outputs.

!!! info "WWA (warm white + cold white + amber white)"
    _*SK6812 WWA (with 3 channels, warm white, cold white and amber) are supported, but treated as if RGB using the `WS281x` bus type. White spectrum support for this LED type will be added at a later point._

The overall brightness of the white channels is determined from the auto-white calculation outlined above, and as such is identical in behavior to that of single white channel busses.

The color temperature is set either on a per-segment basis via a dedicated slider in the UI, or if `Calculate CCT from RGB` is enabled in LED settings, is estimated on a per-pixel basis from the set RGB color (e.g. setting Red results in the warmest, setting Blue results in the coldest possible white).
The former has the advantage of granular white spectrum control independent of the set RGB color, while the latter enables control of the color temperature from all effects and realtime sources.

#### CCT additive blending

Setting this to 0% results in a more even brightness output across the supported temperature range, as the fading between the warm and cold white channels is linear.

Setting this to 100% results in the highest peak brightness output at the neutral white point (CCT value `127`), as both white channels are active at 100%.

![](/assets/images/content/wledcct.png)

!!! warning "Additive Blending May Cause Heatup"
	Make sure your setup can handle driving both white channels at maximum output simultaneously. This results in a higher heat output and might reduce the lifetime of your LEDs. For example, bulbs by Athom are designed for linear blending (0%) and may be damaged by attempting to use additive blending.

You can limit the maximum allowed additive blending at build time using the `WLED_MAX_CCT_BLEND` macro.  
For example, add `-D WLED_MAX_CCT_BLEND=0` to your build flags to force linear blending only.

#### IC CCT

By default, PWM CCT bus types set the value of the warm and cold white channels.  
If your hardware uses an IC that controls the color temperature based on one PWM signal and the overall brightness on the other, please use the build flag `-D WLED_USE_IC_CCT` in a custom compilation. (the 15W bulb by Athom uses this method)

#### CCT in the JSON API

See [CCT control in the JSON API](/interfaces/json-api/#cct-control) for integration details.



---
title: Effects
hide:
  # - navigation
  # - toc
---

!!! info "Version Info"
    Effects above 117 are only available 0.14+ or Sound Reactive forks.  
    v16.0 adds 36 new effects — see [Effects available since 16.0](#effects-available-since-160) below.  
    [Retired Effects](#retired-effects) - Can't find an old favorite? Look here.

## New in v16.0

v16.0 adds **36 new effects** across 1D, 2D, and the Particle System:

**1D Particle System effects** (requires [Particle System](/features/particle-system)):
PS DripDrop, PS Pinball, PS Dancing Shadows, PS Fireworks 1D, PS Sparkler, PS Hourglass, PS Spray 1D, PS 1D Balance, PS Chase, PS Starburst, PS GEQ 1D, PS Fire 1D, PS Sonic Stream, PS Sonic Boom, PS Spring

**2D Particle System effects** (requires a 2D segment):
PS Fire, PS Waterfall, PS Vortex, PS Fireworks, PS Volcano, PS Ballpit, PS Box, PS Fuzzy Noise, PS Impact, PS Attractor, PS Spray, PS GEQ Nova, PS Ghost Rider, PS Blobs, PS Galaxy, PS GEQ 2D

**Other new effects:**
PacMan, Shimmer, Color Clouds, Image, Slow Transition, Copy Segment

**user_fx usermod effects** (requires `user_fx` usermod build):
Diffusion Fire, Spinning Wheel, Lava Lamp, Magma, Ants, Morse Code, PS Comet

## Effect Overlay
Since 16.0 true segment & effect overlay is supported.

To use overlay, set up segments with overlapping pixels. Multiple segments can be composited. For each segment, you can select the overlay mode:

| Mode | Description |
|------|-------------|
| Top/Default | Shows only the top layer, ignoring the bottom entirely |
| Bottom/None | Shows only the bottom layer, ignoring the top entirely |
| Add | Adds colors together, clamping at white |
| Subtract | Subtracts the top from the bottom, darkening toward black |
| Difference | Absolute difference between layers — identical colors go black, opposites go bright |
| Average | Evenly blends both layers at 50% each |
| Multiply | Multiplies colors together — white acts as a mask to bottom layer |
| Divide | Divides bottom by top — brightens the bottom where the top is dark |
| Lighten | Picks the brighter of the two layers pixel-by-pixel. |
| Darken | Picks the darker of the two layers pixel-by-pixel. |
| Screen | Inverse of multiply — always brightens, white wins, black is neutral. |
| Overlay | Multiplies dark areas and screens bright areas of the bottom layer — boosts contrast. |
| Hard Light | Like overlay but driven by the top layer — top controls contrast boosting. |
| Soft Light | Softer version of overlay — subtle contrast and saturation boost, no clipping. |
| Dodge | Brightens the bottom layer based on the top — light top = strong brightening. |
| Burn | Darkens the bottom layer based on the top — dark top = strong darkening. |
| Stencil | Shows top where it has any color, bottom where it is black. |

In older WLED versions not all effects do support overlay and the overlay effect must be playing on the segment with the higher id.
If the Overlay option is checked, the background will not be painted and the effect
from the lower segment will be displayed.

To aid in showing where colors vs palettes are used, all effects are rendered with the 
_Party_ palette ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_06.gif)<br />
and the colors: <br />
![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/color_1.gif) Primary (_Fx_)<br />
![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/color_2.gif) (or black) Secondary  (_Bg_)<br />
![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/color_3.gif) Tertiary (_Cs_).<br />
For 2D effects the background (secondary) color is set to black.

## Effects

|  ID | Effect              | Description                                                                                                                                                                                                                                                            | Flags | Colors                                  | Parameters                                                                      |
|:----|---------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------|-----------------------------------------|-------------------------------------------------------------------------------|
| 186 | Akemi               | The WLED mascot rocking to your tunes. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_186.gif){ width="300" }                                                                                                                                    | ▦ ♫   | Head palette, Arms & Legs, Eyes & Mouth | Color speed, Dance                                                            |
|  27 | Android             | Section of varying length running <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_027.gif){ width="300" }                                                                                                                                         | ⋮     | 🎨 Fx, Bg                               | Speed, Width                                                                  |
|  38 | Aurora              | Simulation of the Aurora Borealis <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_038.gif){ width="300" }                                                                                                                                         | ⋮     | 🎨 1, 2, 3                              | Speed, Intensity                                                              |
| 183 | Black Hole          | Colorful dots orbiting a white black hole. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_183.gif){ width="300" }                                                                                                                                | ▦     | 🎨 Fx                                   | Fade rate, Outer Y freq., Outer X freq., Inner X freq., Inner Y freq., Solid  |
| 115 | Blends              | Blends random colors across palette <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_115.gif){ width="300" }                                                                                                                                       | ⋮     | 🎨                                      | Shift speed, Blend speed                                                      |
|   1 | Blink               | Blinks between primary and secondary color <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_001.gif){ width="300" }                                                                                                                                | ⋮     | 🎨 Fx, Bg                               | Speed, Duty cycle                                                             |
|  26 | Blink Rainbow       | Same as blink, cycles through the rainbow <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_026.gif){ width="300" }                                                                                                                                 | ⋮     | 🎨 Fx, Bg                               | Frequency, Blink duration                                                     |
| 121 | Blobs               | No really, they are blobs. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_121.gif){ width="300" }                                                                                                                                                | ▦     | 🎨 Fx                                   | Speed, # blobs, Blur                                                          |
| 163 | Blurz               | Flash an fftResult bin per frame and then blur/fade. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_163.gif){ width="300" }                                                                                                                      | ⋮ ♫   | 🎨 Fx, Color mix                        | Fade rate, Blur                                                               |
|  91 | Bouncing Balls      | Bouncing ball effect <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_091.gif){ width="300" }                                                                                                                                                      | ⋮     | 🎨 Fx, Bg, Cs                           | Gravity, # of balls, Overlay                                                  |
|  68 | Bpm                 | Pulses moving back and forth on palette <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_068.gif){ width="300" }                                                                                                                                   | ⋮     | 🎨 Fx                                   | Speed                                                                         |
|   2 | Breathe             | Fades between primary and secondary color <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_002.gif){ width="300" }                                                                                                                                 | ⋮     | 🎨 Fx, Bg                               | Speed                                                                         |
|  88 | Candle              | Flicker resembling a candle flame <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_088.gif){ width="300" }                                                                                                                                         | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
| 102 | Candle Multi        | Like candle effect, but each LED has it's own flicker pattern <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_102.gif){ width="300" }                                                                                                             | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
|  28 | Chase               | 2 LEDs in primary color running on secondary <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_028.gif){ width="300" }                                                                                                                              | ⋮     | 🎨 Fx, Bg, Cs                           | Speed, Width                                                                  |
|  37 | Chase 2             | Pattern of n LEDs primary and n LEDs secondary moves along the strip <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_037.gif){ width="300" }                                                                                                      | ⋮     | 🎨 Fx, Bg                               | Speed, Width                                                                  |
|  54 | Chase 3             | Like Chase, but with 3 colors <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_054.gif){ width="300" }                                                                                                                                             | ⋮     | 🎨 1, 2, 3                              | Speed, Size                                                                   |
|  31 | Chase Flash         | 2 LEDs flash in secondary color while the rest is lit in primary. The flashing LEDs wander from start to end <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_031.gif){ width="300" }                                                              | ⋮     | 🎨 Bg, Fx                               | Speed                                                                         |
|  32 | Chase Flash Rnd     | Like Chase Flash, but the 2 LEDs flash in random colors and leaves a random color behind <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_032.gif){ width="300" }                                                                                  | ⋮     | 🎨 Fx, Bg                               | Speed                                                                         |
|  30 | Chase Rainbow       | Like 28 but leaves trail of rainbow <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_030.gif){ width="300" }                                                                                                                                       | ⋮     | 🎨 Fx, Bg                               | Speed, Width                                                                  |
|  29 | Chase Random        | Like Chase but leaves trail of random color <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_029.gif){ width="300" }                                                                                                                               | ⋮     | 🎨 Fx, Cs                               | Speed, Width                                                                  |
| 111 | Chunchun            | Birds flying in a circle formation <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_111.gif){ width="300" }                                                                                                                                        | ⋮     | 🎨 Fx, Bg                               | Speed, Gap size                                                               |
| 167 | Colored Bursts      | Rotating rays of color. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_167.gif){ width="300" }                                                                                                                                                   | ▦     | 🎨                                      | Speed, # of lines, Blur, Gradient, Dots                                       |
|  34 | Colorful            | Shifting Red-Amber-Green-Blue pattern <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_034.gif){ width="300" }                                                                                                                                     | ⋮     | 🎨 1, 2, 3                              | Speed, Saturation                                                             |
|   8 | Colorloop           | Cycle all LEDs through the rainbow colors <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_008.gif){ width="300" }                                                                                                                                 | ⋮     | 🎨                                      | Speed, Saturation                                                             |
|  74 | Colortwinkles       | LEDs light up randomly in random colors and fade off again <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_074.gif){ width="300" }                                                                                                                | ⋮     | 🎨                                      | Fade speed, Spawn speed                                                       |
|  67 | Colorwaves          | Like Pride 2015, but uses palettes <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_067.gif){ width="300" }                                                                                                                                        | ⋮     | 🎨 Fx                                   | Speed, Hue                                                                    |
| 119 | Crazy Bees          | Bees darting from flower to flower. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_119.gif){ width="300" }                                                                                                                                       | ▦     |                                         | Speed, Blur                                                                   |
| 159 | DJ Light            | An effect emanating from the center to the edges. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_159.gif){ width="300" }                                                                                                                         | ⋮ ♫   |                                         | Speed                                                                         |
| 152 | DNA                 | A very cool DNA like pattern. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_152.gif){ width="300" }                                                                                                                                             | ▦     | 🎨                                      | Scroll speed, Blur                                                            |
| 182 | DNA Spiral          | Spiraling DNA pattern <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_182.gif){ width="300" }                                                                                                                                                     | ▦     | 🎨                                      | Scroll speed, Y frequency                                                     |
| 112 | Dancing Shadows     | Moving spotlights <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_112.gif){ width="300" }                                                                                                                                                         | ⋮     | 🎨 Fx                                   | Speed, # of shadows                                                           |
|  18 | Dissolve            | Fills LEDs with primary in random order, then off again <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_018.gif){ width="300" }                                                                                                                   | ⋮     | 🎨 Fx, Bg                               | Repeat speed, Dissolve speed, Random                                          |
|  19 | Dissolve Rnd        | Fills LEDs with random colors in random order, then off again <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_019.gif){ width="300" }                                                                                                             | ⋮     | 🎨 Bg                                   | Repeat speed, Dissolve speed                                                  |
| 124 | Distortion Waves    | Distorted sine waves with a psychedelic flair. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_124.gif){ width="300" }                                                                                                                            | ▦     |                                         | Speed, Scale                                                                  |
| 164 | Drift               | A rotating kaleidoscope. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_164.gif){ width="300" }                                                                                                                                                  | ▦     | 🎨                                      | Rotation speed, Blur amount                                                   |
| 123 | Drift Rose          | Spinning arms that adds and removes nodes as it winds and unwinds. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_123.gif){ width="300" }                                                                                                        | ▦     |                                         | Fade, Blur                                                                    |
|  96 | Drip                | Water dripping effect <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_096.gif){ width="300" }                                                                                                                                                     | ⋮     | 🎨 Fx, Bg                               | Gravity, # of drips, Overlay                                                  |
|   7 | Dynamic             | Sets each LED to a random color <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_007.gif){ width="300" }                                                                                                                                           | ⋮     | 🎨                                      | Speed, Intensity, Smooth                                                      |
| 117 | Dynamic Smooth      | Like Dynamic, but with smooth palette blends <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_117.gif){ width="300" }                                                                                                                              | ⋮     | 🎨                                      | Speed, Intensity                                                              |
|  12 | Fade                | Fades smoothly between primary and secondary color <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_012.gif){ width="300" }                                                                                                                        | ⋮     | 🎨 Fx, Bg                               | Speed                                                                         |
|  49 | Fairy               | Inspired by twinkle style Christmas lights. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_049.gif){ width="300" }                                                                                                                               | ⋮     | 🎨 Fx, Bg                               | Speed, # of flashers                                                          |
|  51 | Fairytwinkle        | Like Colortwinkle, but starting from all lit <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_051.gif){ width="300" }                                                                                                                              | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
|  69 | Fill Noise          | Noise pattern <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_069.gif){ width="300" }                                                                                                                                                             | ⋮     | 🎨 Fx                                   | Speed                                                                         |
|  66 | Fire 2012           | Simulates flickering fire in red and yellow <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_066.gif){ width="300" }                                                                                                                               | ⋮     | 🎨                                      | Cooling, Spark rate, Boost                                                    |
|  45 | Fire Flicker        | LEDs randomly flickering <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_045.gif){ width="300" }                                                                                                                                                  | ⋮     | 🎨 Fx                                   | Speed, Intensity                                                              |
| 149 | Firenoise           | Using Perlin Noise for fire. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_149.gif){ width="300" }                                                                                                                                              | ▦     | 🎨                                      | X scale, Y scale                                                              |
|  42 | Fireworks           | Random color blobs light up, then fade again <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_042.gif){ width="300" }                                                                                                                              | ⋮ ▦   | 🎨 Fx, Bg                               | Frequency                                                                     |
|  90 | Fireworks 1D        | one dimension fireworks with flare <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_090.gif){ width="300" }                                                                                                                                        | ⋮ ▦   | 🎨 Fx, Bg                               | Gravity, Firing side                                                          |
|  89 | Fireworks Starburst | Exploding multicolor fireworks <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_089.gif){ width="300" }                                                                                                                                            | ⋮     | 🎨 Bg                                   | Chance, Fragments, Overlay                                                    |
| 110 | Flow                | Blend of palette and spot effects <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_110.gif){ width="300" }                                                                                                                                         | ⋮     | 🎨                                      | Speed, Zones                                                                  |
| 179 | Flow Stripe         | Strip with rotating colours. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_179.gif){ width="300" }                                                                                                                                              | ⋮     |                                         | Hue speed, Effect speed                                                       |
| 155 | Freqmap             | Map the loudest frequency throughout the length of the LED's. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_155.gif){ width="300" }                                                                                                             | ⋮ ♫   | 🎨 Fx, Bg                               | Fade rate, Starting color                                                     |
| 138 | Freqmatrix          | The temporal tail for this animation starts at the beginning of the Segment rather than in the center of the segment. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_138.gif){ width="300" }                                                     | ⋮ ♫   |                                         | Speed, Sound effect, Low bin, High bin, Sensivity                             |
| 141 | Freqpixels          | Random pixels coloured by frequency. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_141.gif){ width="300" }                                                                                                                                      | ⋮ ♫   |                                         | Fade rate, Starting color and # of pixels                                     |
| 137 | Freqwave            | Maps the major frequencies from the incoming signal to colors in the HSV color space. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_137.gif){ width="300" }                                                                                     | ⋮ ♫   |                                         | Speed, Sound effect, Low bin, High bin, Pre-amp                               |
| 177 | Frizzles            | Moving patterns. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_177.gif){ width="300" }                                                                                                                                                          | ▦     | 🎨                                      | X frequency, Y frequency, Blur                                                |
| 160 | Funky Plank         | A 2D wall of reactivity running from bottom to top <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_160.gif){ width="300" }                                                                                                                        | ▦ ♫   |                                         | Scroll speed, # of bands                                                      |
| 139 | GEQ                 | A 16x16 graphic equalizer. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_139.gif){ width="300" }                                                                                                                                                | ▦ ♫   | 🎨 Fx, Peaks                            | Fade speed, Ripple decay, # of bands, Color bars                              |
| 172 | Game Of Life        | Scrolling game of life. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_172.gif){ width="300" }                                                                                                                                                   | ▦     | 🎨 Fx, Bg                               | Speed                                                                         |
| 120 | Ghost Rider         | Color changing ghost riding a kite... in a tornado. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_120.gif){ width="300" }                                                                                                                       | ▦     | 🎨                                      | Fade rate, Blur                                                               |
|  87 | Glitter             | Rainbow with white sparkles <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_087.gif){ width="300" }                                                                                                                                               | ⋮     | 🎨 1, 2, Glitter color                  | Speed, Intensity, Overlay                                                     |
|  46 | Gradient            | Moves a saturation gradient of the primary color along the strip <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_046.gif){ width="300" }                                                                                                          | ⋮     | 🎨 Fx, Bg                               | Speed, Spread                                                                 |
| 156 | Gravcenter          | Volume reactive vu-meter from center with gravity and perlin noise. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_156.gif){ width="300" }                                                                                                       | ⋮ ♪   | 🎨 Fx, Bg                               | Rate of fall, Sensitivity                                                     |
| 157 | Gravcentric         | Volume reactive vu-meter from center with gravity. Volume provides index to (time rotating) palette colour. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_157.gif){ width="300" }                                                               | ⋮ ♪   | 🎨 Fx, Bg                               | Rate of fall, Sensitivity                                                     |
| 158 | Gravfreq            | VU Meter from center. Log of frequency is index to center colour. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_158.gif){ width="300" }                                                                                                         | ⋮ ♫   | 🎨 Fx, Bg                               | Rate of fall, Sensivity                                                       |
| 132 | Gravimeter          | Volume reactive vu-meter with gravity and perlin noise. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_132.gif){ width="300" }                                                                                                                   | ⋮ ♪   | 🎨 Fx, Bg                               | Rate of fall, Sensitivity                                                     |
|  82 | Halloween Eyes      | One Pair of blinking eyes at random intervals along strip <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_082.gif){ width="300" }                                                                                                                 | ⋮ ▦   | 🎨 Fx, Bg                               | Duration, Eye fade time, Overlay                                              |
| 100 | Heartbeat           | led strip pulsing rhythm similar to a heart beat <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_100.gif){ width="300" }                                                                                                                          | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
| 180 | Hiphotic            | A moving plasma. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_180.gif){ width="300" }                                                                                                                                                          | ▦     | 🎨 Fx                                   | X scale, Y scale, Speed                                                       |
|  58 | ICU                 | Two "eyes" running on opposite sides of the strip <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_058.gif){ width="300" }                                                                                                                         | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity, Overlay                                                     |
|  64 | Juggle              | Eight colored dots running, leaving trails <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_064.gif){ width="300" }                                                                                                                                | ⋮     | 🎨                                      | Speed, Trail                                                                  |
| 130 | Juggles             | Juggling balls. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_130.gif){ width="300" }                                                                                                                                                           | ⋮ ♪   | 🎨 Fx, Bg                               | Speed, # of balls                                                             |
| 168 | Julia               | Animated Julia set fractal named after mathematician Gaston Julia. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_168.gif){ width="300" }                                                                                                        | ▦     | 🎨 Fx                                   | Max iterations per pixel, X center, Y center, Area size                       |
|  75 | Lake                | Calm palette waving <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_075.gif){ width="300" }                                                                                                                                                       | ⋮     | 🎨 Fx                                   | Speed                                                                         |
|  41 | Lighthouse          | Dot moves from start to end, leaving behind a fading trail <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_041.gif){ width="300" }                                                                                                                | ⋮     | 🎨 Fx, Bg                               | Speed, Fade rate                                                              |
|  57 | Lightning           | Short random white strobe similar to a lightning bolt <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_057.gif){ width="300" }                                                                                                                     | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity, Overlay                                                     |
| 176 | Lissajous           | A frequency based Lissajous pattern. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_176.gif){ width="300" }                                                                                                                                      | ▦     | 🎨 Fx                                   | X frequency, Fade rate, Speed                                                 |
|  47 | Loading             | Moves a sawtooth pattern along the strip <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_047.gif){ width="300" }                                                                                                                                  | ⋮     | 🎨 Fx, Bg                               | Speed, Fade                                                                   |
| 131 | Matripix            | Similar to Matrix. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_131.gif){ width="300" }                                                                                                                                                        | ⋮ ♪   | 🎨 Fx, Bg                               | Speed, Brightness                                                             |
| 153 | Matrix              | The Matrix, on a 2D matrix. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_153.gif){ width="300" }                                                                                                                                               | ▦     | Spawn, Trail                            | Speed, Spawning rate, Trail, Custom color                                     |
| 154 | Metaballs           | A cool plasma type effect. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_154.gif){ width="300" }                                                                                                                                                | ▦     | 🎨                                      | Speed                                                                         |
|  76 | Meteor              | The primary color creates a trail of randomly decaying color <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_076.gif){ width="300" }                                                                                                              | ⋮     | 🎨 Fx                                   | Speed, Trail length                                                           |
|  77 | Meteor Smooth       | Smoothly animated meteor <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_077.gif){ width="300" }                                                                                                                                                  | ⋮     | 🎨 Fx                                   | Speed, Trail length                                                           |
| 135 | Midnoise            | Perlin noise emanating from center. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_135.gif){ width="300" }                                                                                                                                       | ⋮ ♪   | 🎨 Fx, Bg                               | Fade rate, Max. length                                                        |
|  59 | Multi Comet         | Like Scanner, but creates multiple trails <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_059.gif){ width="300" }                                                                                                                                 | ⋮     |                                         |                                                                               |
|  70 | Noise 1             | Fast Noise shift pattern <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_070.gif){ width="300" }                                                                                                                                                  | ⋮     | 🎨 Fx                                   | Speed                                                                         |
|  71 | Noise 2             | Fast Noise shift pattern <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_071.gif){ width="300" }                                                                                                                                                  | ⋮     | 🎨 Fx                                   | Speed                                                                         |
|  72 | Noise 3             | Noise shift pattern <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_072.gif){ width="300" }                                                                                                                                                       | ⋮     | 🎨 Fx                                   | Speed                                                                         |
|  73 | Noise 4             | Noise sparkle pattern <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_073.gif){ width="300" }                                                                                                                                                     | ⋮     | 🎨 Fx                                   | Speed                                                                         |
| 107 | Noise Pal           | Peaceful noise that's slow and with gradually changing palettes <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_107.gif){ width="300" }                                                                                                           | ⋮     | 🎨                                      | Speed, Scale                                                                  |
| 146 | Noise2D             | <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_146.gif){ width="300" }                                                                                                                                                                           | ▦     | 🎨                                      | Speed, Scale                                                                  |
| 143 | Noisefire           | A perlin noise based volume reactive fire routine. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_143.gif){ width="300" }                                                                                                                        | ⋮ ♪   |                                         | Speed, Intensity                                                              |
| 136 | Noisemeter          | Volume reactive vu-meter. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_136.gif){ width="300" }                                                                                                                                                 | ⋮ ♪   | 🎨 Fx, Bg                               | Fade rate, Width                                                              |
| 145 | Noisemove           | Using perlin noise as movement for different frequency bins. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_145.gif){ width="300" }                                                                                                              | ⋮ ♫   | 🎨 Fx, Bg                               | Speed of perlin movement, Fade rate                                           |
| 126 | Octopus             | A cephalopod stuck in a whirlpool. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_126.gif){ width="300" }                                                                                                                                        | ▦     | 🎨                                      | Speed, Offset X, Offset Y, Legs                                               |
|  62 | Oscillate           | Areas of primary and secondary colors move between opposite ends, combining colors where they touch <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_062.gif){ width="300" }                                                                       | ⋮     |                                         |                                                                               |
| 101 | Pacifica            | Gentle ocean waves <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_101.gif){ width="300" }                                                                                                                                                        | ⋮     | 🎨                                      | Speed, Angle                                                                  |
|  65 | Palette             | Running color palette <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_065.gif){ width="300" }                                                                                                                                                     | ⋮     | 🎨                                      | Cycle speed                                                                   |
|  98 | Percent             | Lights up a percentage of segment <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_098.gif){ width="300" }                                                                                                                                         | ⋮     | 🎨 Fx, Bg                               | % of fill, One color                                                          |
| 147 | Perlin Move         | Using Perlin Noise for movement. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_147.gif){ width="300" }                                                                                                                                          | ⋮     | 🎨 Fx, Bg                               | Speed, # of pixels, Fade rate                                                 |
| 105 | Phased              | Sine waves (in sourcecode) <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_105.gif){ width="300" }                                                                                                                                                | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
| 109 | Phased Noise        | Noisy sine waves <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_109.gif){ width="300" }                                                                                                                                                          | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
| 128 | Pixels              | Random pixels <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_128.gif){ width="300" }                                                                                                                                                             | ⋮ ♪   | 🎨 Fx, Bg                               | Fade rate, # of pixels                                                        |
| 129 | Pixelwave           | Pixels emanating from center <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_129.gif){ width="300" }                                                                                                                                              | ⋮ ♪   | 🎨 Fx, Bg                               | Speed, Sensitivity                                                            |
|  97 | Plasma              | Plasma lamp <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_097.gif){ width="300" }                                                                                                                                                               | ⋮     | 🎨 Fx                                   | Phase, Intensity                                                              |
| 178 | Plasma Ball         | A ball of plasma. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_178.gif){ width="300" }                                                                                                                                                         | ▦     | 🎨                                      | Speed, Fade, Blur                                                             |
| 133 | Plasmoid            | Sine wave based plasma. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_133.gif){ width="300" }                                                                                                                                                   | ⋮ ♪   | 🎨 Fx, Bg                               | Phase, # of pixels                                                            |
| 174 | Polar Lights        | The northern lights. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_174.gif){ width="300" }                                                                                                                                                      | ▦     |                                         | Speed, Scale                                                                  |
|  95 | Popcorn             | popping kernels <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_095.gif){ width="300" }                                                                                                                                                           | ⋮     | 🎨 Fx, Bg, Cs                           | Speed, Intensity, Overlay                                                     |
|  63 | Pride 2015          | Rainbow cycling with brightness variation <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_063.gif){ width="300" }                                                                                                                                 | ⋮     |                                         | Speed                                                                         |
| 144 | Puddlepeak          | Blast coloured puddles randomly up and down the strand with the 'beat'. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_144.gif){ width="300" }                                                                                                   | ⋮ ♪   | 🎨 Fx, Bg                               | Fade rate, Puddle size, Select bin, Volume (min)                              |
| 134 | Puddles             | Blast coloured puddles based on volume. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_134.gif){ width="300" }                                                                                                                                   | ⋮ ♪   | 🎨 Fx, Bg                               | Fade rate, Puddle size                                                        |
| 162 | Pulser              | Travelling waves. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_162.gif){ width="300" }                                                                                                                                                         | ▦     | 🎨                                      | Speed, Blur                                                                   |
|  78 | Railway             | Shows primary and secondary color on alternating LEDs. All LEDs fade to their opposite color and back again <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_078.gif){ width="300" }                                                               | ⋮     | 🎨 1, 2                                 | Speed, Smoothness                                                             |
|  43 | Rain                | Like Fireworks, but the blobs move <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_043.gif){ width="300" }                                                                                                                                        | ⋮ ▦   | 🎨 Fx, Bg                               | Speed, Spawning rate                                                          |
|   9 | Rainbow             | Displays rainbow colors along the whole strip <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_009.gif){ width="300" }                                                                                                                             | ⋮     | 🎨                                      | Speed, Size                                                                   |
|  33 | Rainbow Runner      | Like Chase, but the 2 LEDs light up in rainbow colors and leave a primary color trail <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_033.gif){ width="300" }                                                                                     | ⋮     | 🎨 Bg                                   | Speed, Size                                                                   |
|   5 | Random Colors       | Applies a new random color to all LEDs <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_005.gif){ width="300" }                                                                                                                                    | ⋮     | 🎨                                      | Speed, Fade time                                                              |
|  79 | Ripple              | Effect resembling random water ripples <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_079.gif){ width="300" }                                                                                                                                    | ⋮ ▦   | 🎨 Bg                                   | Speed, Wave #, Overlay                                                        |
| 148 | Ripple Peak         | Peak detection triggers ripples. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_148.gif){ width="300" }                                                                                                                                          | ⋮ ♪   | 🎨 Fx, Bg                               | Fade rate, Max # of ripples, Select bin, Volume (min)                         |
|  99 | Ripple Rainbow      | Like ripple, but with a dimly lit changing background <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_099.gif){ width="300" }                                                                                                                     | ⋮ ▦   | 🎨                                      | Speed, Wave #                                                                 |
| 185 | Rocktaves           | Colours the same for each note between octaves, with sine wave going back and forth. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_185.gif){ width="300" }                                                                                      | ⋮ ♫   | 🎨 Fx, Bg                               |                                                                               |
|  15 | Running             | Sine Waves scrolling <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_015.gif){ width="300" }                                                                                                                                                      | ⋮     | 🎨 Fx, Bg                               | Speed, Wave width                                                             |
|  52 | Running Dual        | Sine waves in both directions <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_052.gif){ width="300" }                                                                                                                                             | ⋮     | 🎨 L, Bg, R                             | Speed, Wave width                                                             |
|  16 | Saw                 | Sawtooth Waves scrolling <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_016.gif){ width="300" }                                                                                                                                                  | ⋮     | 🎨 Fx, Bg                               | Speed, Width                                                                  |
|  10 | Scan                | A single primary colored light wanders between start and end <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_010.gif){ width="300" }                                                                                                              | ⋮     | 🎨 Fx, Bg, Cs                           | Speed, # of dots, Overlay                                                     |
|  11 | Scan Dual           | Same as Scan but uses two lights starting at both ends <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_011.gif){ width="300" }                                                                                                                    | ⋮     | 🎨 Fx, Bg, Cs                           | Speed, # of dots, Overlay                                                     |
|  40 | Scanner             | Dot moves between ends, leaving behind a fading trail <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_040.gif){ width="300" }                                                                                                                     | ⋮     | 🎨 Fx, Bg                               | Speed, Fade rate                                                              |
|  60 | Scanner Dual        | Like Scanner, but with two dots running on opposite sides <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_060.gif){ width="300" }                                                                                                                 | ⋮     | 🎨 Fx, Bg, Cs                           | Speed, Fade rate                                                              |
| 122 | Scrolling Text      | Edit segment name to set text (variables #DATE, #TIME, #DDMM, #MMDD, #HHMM, #HH, #MM; suffix with 0 to have leading 0s, i.e. #DATE0). Use segment grouping to increase text size on a large matrix.<br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_122.gif){ width="300" }                                                                                                          | ▦     | 🎨 Fx, Bg, Gradient                     | Speed, Y Offset, Trail, Font size, Gradient, Overlay, 0                       |
| 181 | Sindots             | Dots revolving in a circle while the 'camera'  <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_181.gif){ width="300" }                                                                                                                            | ▦     | 🎨                                      | Speed, Dot distance, Fade rate, Blur                                          |
| 108 | Sine                | Controllable sine waves <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_108.gif){ width="300" }                                                                                                                                                   | ⋮     |                                         |                                                                               |
|  92 | Sinelon             | Fastled sinusoidal moving eye <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_092.gif){ width="300" }                                                                                                                                             | ⋮     | 🎨 Fx, Bg, Cs                           | Speed, Trail                                                                  |
|  93 | Sinelon Dual        | Sinelon from both directions <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_093.gif){ width="300" }                                                                                                                                              | ⋮     | 🎨 Fx, Bg, Cs                           | Speed, Trail                                                                  |
|  94 | Sinelon Rainbow     | Sinelon in rainbow colours <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_094.gif){ width="300" }                                                                                                                                                | ⋮     | 🎨 Cs                                   | Speed, Trail                                                                  |
| 125 | Soap                | Like soap bubbles, but lasts longer. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_125.gif){ width="300" }                                                                                                                                      | ▦     | 🎨                                      | Speed, Smoothness                                                             |
|   0 | Solid               | Solid primary color on all LEDs <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_000.gif){ width="300" }                                                                                                                                           | ⋮     |                                         |                                                                               |
| 103 | Solid Glitter       | Like Glitter, but with solid color background <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_103.gif){ width="300" }                                                                                                                             | ⋮     | Bg, Glitter color                       | Intensity                                                                     |
|  83 | Solid Pattern       | Speed sets number of LEDs on, intensity sets off <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_083.gif){ width="300" }                                                                                                                          | ⋮     | 🎨 Fg, Bg                               | Fg size, Bg size                                                              |
|  84 | Solid Pattern Tri   | Solid Pattern with three colors <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_084.gif){ width="300" }                                                                                                                                           | ⋮     | 1, 2, 3                                 | Size                                                                          |
| 118 | Spaceships          | Circling ships with fading trails. Homage to 80s spaceship shooter games. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_118.gif){ width="300" }                                                                                                 | ▦     | 🎨                                      | Speed, Blur                                                                   |
|  20 | Sparkle             | Single random LEDs light up in the primary color for a short time, secondary is background <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_020.gif){ width="300" }                                                                                | ⋮     | 🎨 Fx, Bg                               | Speed, Overlay                                                                |
|  21 | Sparkle Dark        | All LEDs are lit in the primary color, single random LEDs turn off for a short time <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_021.gif){ width="300" }                                                                                       | ⋮     | 🎨 Bg, Fx                               | Speed, Intensity, Overlay                                                     |
|  22 | Sparkle+            | All LEDs are lit in the primary color, multiple random LEDs turn off for a short time <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_022.gif){ width="300" }                                                                                     | ⋮     | 🎨 Bg, Fx                               | Speed, Intensity, Overlay                                                     |
|  85 | Spots               | Solid lights with even distance <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_085.gif){ width="300" }                                                                                                                                           | ⋮     | 🎨 Fx, Bg                               | Spread, Width, Overlay                                                        |
|  86 | Spots Fade          | Spots, getting bigger and smaller <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_086.gif){ width="300" }                                                                                                                                         | ⋮     | 🎨 Fx, Bg                               | Spread, Width, Overlay                                                        |
| 150 | Squared Swirl       | Boxes moving around <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_150.gif){ width="300" }                                                                                                                                                       | ▦     | 🎨                                      | Blur                                                                          |
|  39 | Stream              | Flush bands random hues along the string <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_039.gif){ width="300" }                                                                                                                                  | ⋮     | 🎨                                      | Speed, Zone size                                                              |
|  61 | Stream 2            | Flush random hues along the string <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_061.gif){ width="300" }                                                                                                                                        | ⋮     |                                         | Speed                                                                         |
|  23 | Strobe              | All LEDs are lit in the secondary color, all LEDs flash in a single short burst in primary color <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_023.gif){ width="300" }                                                                          | ⋮     | 🎨 Fx, Bg                               | Speed                                                                         |
|  25 | Strobe Mega         | All LEDs are lit in the secondary color, all LEDs flash in several short bursts in primary color <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_025.gif){ width="300" }                                                                          | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
|  24 | Strobe Rainbow      | Same as strobe, cycles through the rainbow <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_024.gif){ width="300" }                                                                                                                                | ⋮     | 🎨 Bg                                   | Speed                                                                         |
| 166 | Sun Radiation       | The sun! Doesn't support segments. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_166.gif){ width="300" }                                                                                                                                        | ▦     |                                         | Variance, Brightness                                                          |
| 104 | Sunrise             | Simulates a gradual sunrise or sunset. Speed sets: 0 - static sun, 1 - 60: sunrise time in minutes,60 - 120: sunset time in minutes - 60, above: "breathing" rise and set <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_104.gif){ width="300" } | ⋮     | 🎨                                      | Time [min], Width                                                             |
|   6 | Sweep               | Switches between primary and secondary, switching LEDs one by one, start to end to start <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_006.gif){ width="300" }                                                                                  | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
|  36 | Sweep Random        | Like Sweep, but uses random colors <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_036.gif){ width="300" }                                                                                                                                        | ⋮     | 🎨                                      | Speed                                                                         |
| 175 | Swirl               | Several blurred circles. Looks good with pink plasma palette. Supports AGC. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_175.gif){ width="300" }                                                                                               | ▦ ♪   | 🎨 Bg Swirl                             | Speed, Sensitivity, Blur                                                      |
| 116 | TV Simulator        | TV light spill simulation <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_116.gif){ width="300" }                                                                                                                                                 | ⋮     |                                         | Speed, Intensity                                                              |
| 173 | Tartan              | Plaid pattern of horizontal and vertical bands. Makes a great kilt. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_173.gif){ width="300" }                                                                                                       | ▦     | 🎨                                      | X scale, Y scale, Sharpness                                                   |
|  44 | Tetrix              | Falling blocks stack <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_044.gif){ width="300" }                                                                                                                                                      | ⋮     | 🎨 Fx, Bg                               | Speed, Width, One color                                                       |
|  13 | Theater             | Pattern of one lit and two unlit LEDs running <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_013.gif){ width="300" }                                                                                                                             | ⋮     | 🎨 Fx, Bg                               | Speed, Gap size                                                               |
|  14 | Theater Rainbow     | Same as Theater but uses colors of the rainbow <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_014.gif){ width="300" }                                                                                                                            | ⋮     | 🎨 Bg                                   | Speed, Gap size                                                               |
|  35 | Traffic Light       | Emulates a traffic light <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_035.gif){ width="300" }                                                                                                                                                  | ⋮     | 🎨 Bg                                   | Speed, US style                                                               |
|  56 | Tri Fade            | Fades the whole strip from primary color to secondary color to off <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_056.gif){ width="300" }                                                                                                        | ⋮     | 🎨 1, 2, 3                              | Speed                                                                         |
|  55 | Tri Wipe            | Like Wipe but turns LEDs off as "third color" <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_055.gif){ width="300" }                                                                                                                             | ⋮     | 🎨 1, 2, 3                              | Speed                                                                         |
|  17 | Twinkle             | Random LEDs light up in the primary color with secondary as background <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_017.gif){ width="300" }                                                                                                    | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
|  81 | Twinklecat          | Twinkling with fast in / slow out <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_081.gif){ width="300" }                                                                                                                                         | ⋮     | 🎨                                      | Speed, Twinkle rate                                                           |
|  80 | Twinklefox          | FastLED gentle twinkling with slow fade in/out <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_080.gif){ width="300" }                                                                                                                            | ⋮     | 🎨                                      | Speed, Twinkle rate                                                           |
| 106 | Twinkleup           | Twinkle effect with fade-in <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_106.gif){ width="300" }                                                                                                                                               | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
|  50 | Two Dots            | Two areas sweeping <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_050.gif){ width="300" }                                                                                                                                                        | ⋮     | 🎨 1, 2, Bg                             | Speed, Dot size, Overlay                                                      |
| 113 | Washing Machine     | Spins, slows, reverses directions <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_113.gif){ width="300" }                                                                                                                                         | ⋮     | 🎨                                      | Speed, Intensity                                                              |
| 140 | Waterfall           | A volume AND FFT version of a Waterfall that has 'beat' support. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_140.gif){ width="300" }                                                                                                          | ⋮ ♫   | 🎨 Fx, Bg                               | Speed, Adjust color, Select bin, Volume (min)                                 |
| 165 | Waverly             | Noise waves with some sound. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_165.gif){ width="300" }                                                                                                                                              | ▦ ♪   | 🎨                                      | Amplification, Sensitivity                                                    |
| 184 | Wavesins            | Beat waves and phase shifting. Looks OK in 2D'ish as well. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_184.gif){ width="300" }                                                                                                                | ⋮     | 🎨 Fx                                   | Speed, Brightness variation, Starting color, Range of colors, Color variation |
| 127 | Waving Cell         | If a bunch of eucaryotes went to a sports stadium and did the wave, it would look exactly like this. <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_127.gif){ width="300" }                                                                      | ▦     | 🎨                                      | Speed, Amplitude 1, Amplitude 2, Amplitude 3                                  |
|   3 | Wipe                | Switches between primary and secondary, switching LEDs one by one, start to end <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_003.gif){ width="300" }                                                                                           | ⋮     | 🎨 Fx, Bg                               | Speed, Intensity                                                              |
|   4 | Wipe Random         | Same as Wipe, but uses random colors <br /> ![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/FX_004.gif){ width="300" }                                                                                                                                      | ⋮     | 🎨                                      | Speed                                                                         |

### Effects available since 16.0
All new effects support palettes except pacman and image. Effects with the prefix "PS" use the particle system.

!!! info "Image Effect"
    * You can only have _one_ segment playing this effect
    * Segment name must be set to the file name (like "anim1.gif") on the esp32 filesystem.
    * Animated GIFs are _mostly_ supported natively by WLED i.e. even through a direct upload of the GIF using the file editor. 
    * If you experience issues, convert the GIF with the [PixelForge Image Tool](/features/pixelforge#image-tool).
    * Effect is **not available on ESP8266** due to limited RAM

| ID | Effect | Description | Flags | Colors | Parameters |
|:---|:---|:---|:---:|:---:|:---|
| 53 | **Image** | Animated GIF Image. <br /> ![Comets GIF preview](../assets/images/content/effect_gifs/FX_53_comets64.gif){ width="300" } |  ⋮ ▦ | - | **Segment Name**:Image File Name `filename.gif`<br> **Speed:** Animation speed <br> **Blur:** Image blur <br> example image is from [marcmerlin/AnimatedGIFs](https://github.com/marcmerlin/AnimatedGIFs/blob/master/data64_2MB/gifs64/284_comets.gif){ width="300" }|
| 187 | **PS Volcano** | Erupting volcano. <br /> ![](../assets/images/content/effect_gifs/FX_187.gif){ width="300" } | ▦ | 🎨 | **Speed:** Particle speed <br> **Intensity:** Particles emitted <br> **Move:** Movement velocity <br> **Bounce:** Collision hardness <br> **Spread:** Emitter variation <br> **AgeColor:** Color by particle age <br> **Walls:** Enable side boundaries <br> **Collide:** Enable particle-particle collisions |
| 188 | **PS Fire** | Versatile and quite realistic fire effect. <br /> ![](../assets/images/content/effect_gifs/FX_188.gif){ width="300" } | ▦ | 🎨 | **Speed:** Flame speed <br> **Intensity:** Heat intensity <br> **Flame height:** Vertical reach <br> **Wind:** Wind speed <br> **Spread:** Fire width <br> **Smooth:** Enable Smoothing/Blurring <br> **Cylinder:** Wrap left & right <br> **Turbulence:** Add turbulence |
| 189 | **PS Fireworks** | Rockets shooting up and exploding in various ways and colors. <br /> ![](../assets/images/content/effect_gifs/FX_189.gif){ width="300" } | ▦ | 🎨 | **Launches:** Rocket launch frequency <br> **Explosion Size:** size of explosion <br> **Fuse:** Detonation timer <br> **Blur:** Trail softness <br> **Gravity:** Pull force <br> **Cylinder:** Wrap left & right <br> **Ground:** Enable floor <br> **Fast:** Doubles speed |
| 190 | **PS Vortex** | Swirling particle vortex effect. <br /> ![](../assets/images/content/effect_gifs/FX_190.gif){ width="300" } | ▦ | 🎨 | **Rotation Speed:** Spin velocity <br> **Particle Speed:** Radial velocity <br> **Arms:** Spiral count <br> **Flip:** Direction swap frequency <br> **Nozzle:** Emission spread <br> **Smear:** Full blur <br> **Direction:** left/right rotation <br> **Random Flip:** Randomize flip intervals |
| 191 | **PS Fuzzy Noise** | Organic flowing noise-based particle field. <br /> ![](../assets/images/content/effect_gifs/FX_191.gif){ width="300" } | ▦ | 🎨 | **Speed:** Noise change speed <br> **Particles:** Particle count <br> **Bounce:** Particle hardness <br> **Friction:** Movement drag <br> **Scale:** Noise field size <br> **Cylinder:** Wrap left & right <br> **Smear:** Full blur <br> **Collide:** Enable particle-particle collisions |
| 192 | **PS Ballpit** | Falling / bouncing balls simulation. <br /> ![](../assets/images/content/effect_gifs/FX_192.gif){ width="300" } | ▦ | 🎨 | **Speed:** Fall speed <br> **Intensity:** Ball count <br> **Size:** Ball size, max = random<br> **Hardness:** Ball hardness, sticky if very low <br> **Saturation:** Color saturation <br> **Cylinder:** Wrap left & right <br> **Walls:** Side boundaries <br> **Ground:** Bottom floor |
| 193 | **PS Box** | Chaotic particles in a box. <br /> ![](../assets/images/content/effect_gifs/FX_193.gif){ width="300" } | ▦ | 🎨 | **Speed:** Direction change rate <br> **Particles:** Count <br> **Tilt:** Force strength <br> **Hardness:** Bounce hardness <br> **Size:** Particle size, max = random <br> **Random:** Random force instead of circular <br> **Washing Machine:** Spin back and forth <br> **Sloshing:** Rock my boat |
| 194 | **PS Attractor** | Particles swirling around a black hole. <br /> ![](../assets/images/content/effect_gifs/FX_194.gif){ width="300" } | ▦ ♫ | 🎨 | **Mass:** Pull-in strength <br> **Particles:** Count <br> **Size:** Particle size <br> **Collide:** Enable particle-particle collisions <br> **Friction:** Drag <br> **AgeColor:** Color by particle age <br> **Move:** Move the black hole <br> **Swallow:** Particles disappear when too close |
| 195 | **PS Impact** | Colorful meteor shower. <br /> ![](../assets/images/content/effect_gifs/FX_195.gif){ width="300" } | ▦ | 🎨 | **Launches:** Meteor launch frequency <br> **Intensity:** Splash size <br> **Force:** Impact power <br> **Hardness:** Bounce hardness <br> **Blur:** Motion blur <br> **Cylinder:**  Wrap left & right <br> **Walls:** Side collision <br> **Collide:** Enable particle-particle collisions |
| 196 | **PS Waterfall** | Flowing waterfall simulation. <br /> ![](../assets/images/content/effect_gifs/FX_196.gif){ width="300" } | ▦ | 🎨 | **Speed:** Flow velocity <br> **Intensity:** Water density <br> **Variation:** Flow randomness <br> **Collide:** Enable particle-particle collisions <br> **Position:** Waterfall position left/right <br> **Cylinder:**  Wrap left & right <br> **Walls:** Side collision <br> **Ground:** Splash floor |
| 197 | **PS Spray** | Directional particle spray. <br /> ![](../assets/images/content/effect_gifs/FX_197.gif){ width="300" } | ▦ ♫ | 🎨 | **Speed:** Emit velocity <br> **Intensity:** Emit amount <br> **Left/Right:** Spray position <br> **Up/Down:** Spray position <br> **Angle:** Emit angle <br> **Gravity:** Force <br> **Cylinder/Square:** wrap or bounce left & right <br> **Collide:** Enable particle-particle collisions |
| 198 | **PS GEQ 2D** | Particle based audio-reactive equalizer. <br /> ![](../assets/images/content/effect_gifs/FX_198.gif){ width="300" } | ▦ ♫ | 🎨 | **Speed:** Shoot up speed <br> **Intensity:** Emit amount <br> **Diverge:** Spray spread <br> **Bounce:** Ground bounce <br> **Gravity:** Pull down force <br> **Cylinder:** Wrap left & right <br> **Walls:** Side collision <br> **Floor:** Enable Floor |
| 199 | **PS GEQ Nova** | Radial / Rotating audio-reactive equalizer. <br /> ![](../assets/images/content/effect_gifs/FX_199.gif){ width="300" } | ▦ ♫ | 🎨 | **Speed:** Emit speed <br> **Intensity:** Emit amount <br> **Rotation Speed:** Spin <br> **Color Change:** Hue shift speed <br> **Nozzle:** Divergence rate <br> **Direction:** Spin direction |
| 200 | **PS Ghost Rider** | Spiraling trail effect like the original with more options. <br /> ![](../assets/images/content/effect_gifs/FX_200.gif){ width="300" } | ▦ | 🎨 | **Speed:** Travel velocity <br> **Spiral:** Path curl rate <br> **Blur:** Motion blur amount <br> **Color Cycle:** Hue shift rate <br> **Spread:** Trail divergence <br> **AgeColor:** Color by particle age <br> **Walls:** Bounce on boundaries |
| 201 | **PS Blobs** | Blobs moving around randomly. <br /> ![](../assets/images/content/effect_gifs/FX_201.gif){ width="300" } | ▦ ♫ | 🎨 | **Speed:** Movement velocity <br> **Blobs:** Blob count <br> **Size:** Radius <br> **Life:** Respawn interval <br> **Blur:** Motion blur <br> **Wobble:** Cycle shape <br> **Collide:** Enable collisions <br> **Pulsate:** Cycle size |
| 217 | **PS Galaxy** | Rotating galaxy-style star field with "hyper speed" option. <br /> ![](../assets/images/content/effect_gifs/FX_217.gif){ width="300" } | ▦ | 🎨 | **Speed:** Star speed <br> **Intensity:** Emit amount <br> **Size:** Star size <br> **Color:** Color shift speed <br> **Starfield:** Hyper Speed <br> **Trace:** Motion blur |
| 202 | **PS DripDrop** | Dripping liquid particle effect, combines the classic "Drip" and "Rain" effects with many additional options <br /> ![](../assets/images/content/effect_gifs/FX_202.gif){ width="300" } | ⋮ | 🎨 | **Speed:** Fall speed <br> **Intensity:** Drop frequency <br> **Splash:** Splash size <br> **Blur:** Motion blur <br> **Gravity:** Pull down force <br> **Rain:** Rain mode <br> **PushSplash:** Collisions on splash <br> **Smooth:** 2-pixel interpolation |
| 203 | **PS Pinball** | Pinball-style bouncing particles. <br /> ![](../assets/images/content/effect_gifs/FX_203.gif){ width="300" } | ⋮ | 🎨 | **Speed:** Shoot speed <br> **Bounce:** Ball hardness <br> **Size:** Ball size <br> **Blur:** Trail length <br> **Gravity:** Pull down force <br> **Collide:** Enable collisions <br> **Rolling:** Rolling Balls style <br> **Position Color:** Color by position |
| 204 | **PS Dancing Shadows** | Shadows rushing accross the strip. <br /> ![](../assets/images/content/effect_gifs/FX_204.gif){ width="300" } | ⋮ | 🎨 | **Speed:** Movement speed <br> **Intensity:** Number of ghosts <br> **Blur:** Motion blurring <br> **Color Cycle:** Hue shift <br> **Smear:** Maximum blur <br> **Position Color:** Color by position <br> **Smooth:** 2-pixel interpolation |
| 205 | **PS Fireworks 1D** | One-dimensional fireworks effect. <br /> ![](../assets/images/content/effect_gifs/FX_205.gif){ width="300" } | ⋮ | 🎨 | **Gravity:** Pull down speed <br> **Explosion:** Blast size <br> **Firing side:** Starting point prefrence <br> **Blur:** Motion blur <br> **Color:** 0-15: desaturated, 16-23: full color, 24-30: color by speed, max: color by age or color by position, depending on "colorful" check <br> **Colorful:** Random color (may override color slider) <br> **Trail:** Exhaust trail <br> **Smooth:** 2-pixel interpolation |
| 206 | **PS Sparkler** | Versatile sparkler effect. <br /> ![](../assets/images/content/effect_gifs/FX_206.gif){ width="300" } | ⋮ | 🎨 | **Move:** Emitter speed <br> **Intensity:** Fade speed<br> **Saturation:** Color saturation <br> **Blur:** Motion blur <br> **Sparklers:** Sparkle emitter count <br> **Slide:** Moving sparks <br> **Bounce:** Edge bounce <br> **Large:** Large size sparks |
| 207 | **PS Hourglass** | Particles falling like sand in an hourglass. <br /> ![](../assets/images/content/effect_gifs/FX_207.gif){ width="300" } | ⋮ | 🎨 | **Interval:** Drop interval in 1/10s (10=1s, 20=2s) <br> **Density:** Particle count <br> **Color:** set one of the 8 color modes: <br> 0-31: fixed color from palette<br> 32-63: single color<br> 64-95: bi-colored<br> 96-127: tri-colored<br> 128-159: gradient<br> 160-191: multi gradient<br> 192-223: moving gradient<br> 224-255: color by position <br> **Blur:** Motion blur <br> **Gravity:** Fall speed <br> **Colorflip:** Flip color when falling <br> **Start:** Auto start (pause if unchecked) <br> **Fast Reset:** Move to initial position fast |
| 208 | **PS Spray 1D** | Spray emitter: choose your settings. <br /> ![](../assets/images/content/effect_gifs/FX_208.gif){ width="300" } | ⋮ | 🎨 | **Speed(+/-):** Emit velocity (upd/down) <br> **Intensity:** Emit amount <br> **Position:** Spray position <br> **Blur:** Motion blur <br> **Gravity(+/-):** Pull force direction <br> **AgeColor:** Color by age <br> **Bounce:** Edge bounce <br> **Position Color:** Color by position |
| 209 | **PS 1D Balance** | Particles flowing back and forth as if the LEDs were reacting to tilt. <br /> ![](../assets/images/content/effect_gifs/FX_209.gif){ width="300" } | ⋮ | 🎨 | **Speed:** Tilt speed <br> **Intensity:** Number of Particles <br> **Hardness:** Collision hardness <br> **Blur:** Motion blur <br> **Tilt:** Tilt strength <br> **Position Color:** Color by position <br> **Wrap:** Loop edges <br> **Random:** Randomize tilt |
| 210 | **PS Chase** | Particles chasing along the strip in a regular pattern. <br /> ![](../assets/images/content/effect_gifs/FX_210.gif){ width="300" } | ⋮ | 🎨 | **Speed:** Velocity <br> **Density:** Spacing <br> **Size:** Particle width <br> **Hue:** Color interval, max = random <br> **Blur:** Motion blur <br> **Playful:** Changes hue, size, speed and density over time <br> **Position Color:** Color by position |
| 211 | **PS Starburst** | Exploding starburst particles. <br /> ![](../assets/images/content/effect_gifs/FX_211.gif){ width="300" } | ⋮ | 🎨 | **Chance:** Blast frequency <br> **Fragments:** Number of star fragments <br> **Size:** Fragment size <br> **Blur:** Motion blur <br> **Cooling:** Fade time <br> **Gravity:** Pull fragments down <br> **Colorful:** Random colors <br> **Push:** Enable collisions |
| 212 | **PS GEQ 1D** | One-dimensional audio equalizer. <br /> ![](../assets/images/content/effect_gifs/FX_212.gif){ width="300" } | ⋮ ♫ | 🎨 | **Speed:** Particle speed <br> **Intensity:** Particle count <br> **Size:** Particle size <br> **Blur:** Motion blur |
| 213 | **PS Fire 1D** | One-dimensional particle fire effect. <br /> ![](../assets/images/content/effect_gifs/FX_213.gif){ width="300" } | ⋮ | 🎨 | **Speed:** Flame velocity <br> **Intensity:** Heat level <br> **Cooling:** Heat dissipation <br> **Blur:** Motion blur |
| 214 | **PS Sonic Stream** | Flowing audio-reactive stream. <br /> ![](../assets/images/content/effect_gifs/FX_214.gif){ width="300" } | ⋮ ♫ | 🎨 | **Speed:** Flow speed <br> **Intensity:** Emit amount and sensitivity <br> **Color:** Hue increment, min=white, max=color by position <br> **Blur:** Motion blur <br> **Bin:** Frequency to react to <br> **Mod:** Color modulation (mid frequencies) <br> **Filter:** Audio filtering <br> **Push:** Push instead of flow |
| 215 | **PS Sonic Boom** | Audio triggered particle bursts. <br /> ![](../assets/images/content/effect_gifs/FX_215.gif){ width="300" } | ⋮ ♫ | 🎨 | **Speed:** Expansion speed <br> **Intensity:** Boom size <br> **Color:** Hue increment, min=white, max=color by position <br> **Position:** Below mid level: fixed position, above: advance per beat, max=random <br> **Bin:** Frequency to react to <br> **Mod:** Color modulation (mid frequencies) <br> **Filter:** Audio filtering <br> **Blur:** Motion blur |
| 216 | **PS Springy** | Particles connected by springs. <br /> ![](../assets/images/content/effect_gifs/FX_216.gif){ width="300" } | ⋮ | 🎨 | **Stiffness:** Spring tension <br> **Damping:** Dampen oscillations <br> **Density:** Particle count <br> **Hue:** Color gradient, 0=color by density <br> **Mode:** Excitation:  <br>Pulse: 0-5 apply at start, 6-10 apply at center <br> Wave: 11-20 apply at start, 21-30 apply at center<br> >30 apply random pulse<br> **Smear:** Full blur <br> **XL:** Large particles <br> **AR:** Audio reactive mode |
| 161 | **Shimmer** | A shimmer moving accross the strip with optional modulators. <br /> ![](../assets/images/content/effect_gifs/FX_161.gif){ width="300" } | ⋮ | 🎨 | **Speed:** Movement speed <br> **Interval:** Pause time <br> **Size:** Width <br> **Granular:** Granularity size <br> **Flow:** Granularity movement <br> **Zebra:** Regular stripes <br> **Reverse:** Invert direction <br> **Sporadic:** Randomize intervals |
| 218 | **Color Clouds** | Soft and slow evolving color cloud effect. <br /> ![](../assets/images/content/effect_gifs/FX_218.gif){ width="300" } | ⋮ | 🎨 | **Speed:** Cloud movement <br> **Intensity:** Color change speed <br> **Clouds:** Number of clouds <br> **Colors:** Color variation <br> **Distance:** Cloud spacing <br> **Cozy:** Calmer clouds |
| 219 | **Slow Transition** | Very slow transitions up to 255 minutes <br /> ![](../assets/images/content/effect_gifs/FX_219.gif){ width="300" } | ⋮ | 🎨 | **Time (min):** Transition time in minutes <br> **Sweep:** Sweeping color change <br>  **Exmple:** Create a preset with "Solid" FX and the starting color. Create a second preset with this FX and the end color/palette, set the fade time to 10. Create a playlist of these two presets: "Solid" preset 1s duration, set "Slow Transition" preset as end preset. |
| 151 | **PacMan** | Pixel based Pac-Man. <br /> ![](../assets/images/content/effect_gifs/FX_151.gif){ width="300" } | ⋮ |  | **Speed:** Effect speed <br> **# of PowerDots:** Power-up dot density <br> **Blink distance:** Ghost start blinking distance <br> **Blur:** Blurring <br> **# of Ghost:** Number of ghosts <br> **Dots:** Enable dots <br> **Smear:** Persistant tails <br> **Compact** Narrow dots |

### Retired Effects

Some effects get retired when they can be recreated with newer, more general effects.

| Removed Effect  | Replacement                           | Retired After |
|-----------------|---------------------------------------|---------------|
| Candy Cane      | Chase 2 - red/white                   | 0.14.0        |
| Dissolve Rnd    | Dissolve                              | 0.14.0        |
| Dynamic Smooth  | Dynamic                               | 0.14.0        |
| Halloween       | Chase 2                               | 0.14.0        |
| Merry Christmas | Chase 2 - red/green                   | 0.12.0        |    
| Police          | Two Dot                               | 0.14.0        |
| Police All      | Two Dots - red/blue w/ full intensity | 0.13.0        |
| Two Areas       | Two Dots - full intensity             | 0.13.0        |



---
title: Macros
hide:
  # - navigation
  # - toc
---
!!! info
    Also see [Presets](/features/presets) for 0.11.0+.

You are able to set custom actions ("Macros") in Time & Macro settings for the following events:

- Specific time of day
- Button short/long/double press
- HTTP API call executing a macro with `&M=`
- Alexa On/Off
- Countdown over
- Timed light duration over
- Device (re)boot (up to 0.10.2, use LED settings `Boot preset` in 0.11)

Note: If you have multiple presets that run at the same time, the lowest down the list takes precedence.

Each macro has the format of a standard [HTTP API call](/interfaces/http-api) without the IP. Optionally, the "win&" may be omitted.
For example, the macro "A=255" sets the brightness to maximum. "R=255&G=160&B=0" sets the color to orange.
You can specify up to 16 macros. (up to 250 in WLED 0.11 since the Macro functionality has been merged into the Presets feature)

Examples of how to use API-calls and define macros can be found in [this issue](https://github.com/wled/WLED/issues/801#issuecomment-635600255) and [in this one](https://github.com/wled/WLED/issues/199#issuecomment-520143239).

The simplest macro example is getting a button to do your bidding.  The default pin to which a button can be connected is GPIO 0 (D3 on NodeMCU, D1 Mini and others).  Even though WLED uses the internal pull up resistors on input pins, this pin is ideally externally pulled high to 3.3V with a 10k resistor. The configured macro executes when the pin is pulled low (grounded). The desired macro is entered on the Time/Macros configuration page and then assigned to a short, long or double press. Like this:

![image](../assets/images/content/macros-button-assignment.png)


The "T=2" macro toggles power to the LEDs (in this case long press).
The "FX=~" macro steps through the effects (in this case short press).

You can set a preset to `P1=1&P2=3&PL=~`, enter the preset number for your button, and this will step through presets 1 and 3. Change the "3" to whatever your highest preset is that you want to include.

The default (built-in) actions for button 0 are short-press: toggle on/off and long-press: select random color.
Long-pressing for more than 6 seconds will open the WLED-AP with the default password (`wled1234`).  
For further buttons, the default action for short press is cycling effects, long press ramp brightness, and double press cycle palettes.

## Buttons

Multiple buttons are implemented since 0.13. Starting in v16.0, up to **32 buttons** can be configured without any custom compilation — use the LED Settings page to add as many as you need.

The following button types are supported:

- momentary push-buttons that are normally open and short GPIO pin to ground (active low)
- momentary push-buttons that are normally closed and release the connection from GPIO pin to GND (inverted, active high)
- switches (be careful with selection of GPIO for switch since some GPIOs will prevent successful boot of ESP if held LOW or HIGH at boot)
- PIR switch AKA motion detection sensor (they set GPIO HIGH when motion is detected, this type of buttons will also trigger MQTT message with /motion topic if "Publish on button press" is set on MQTT config)
- some GPIO pins on ESP32 can act as momentary touch buttons with no additional hardware
- analog "buttons" (also with inverted logic) those can be used as potentiometers or analog input buttons

Button GPIO pin and type can be selected in the _LED Settings_ page.

Each momentary button can have 3 different [Presets](/features/presets) assigned, for short press, long press or double press.
Momentary push-buttons by default trigger shortly after the _release_ of a button, to be able to detect if it has been pressed short, long or twice. When configuring the same preset number for short, long and double press, it will trigger directly when being pressed as of WLED 0.14.0-b2-2306020.

For switch type buttons you can assign only 2 presets, one for transition of switch from LOW to HIGH and second for the opposite transition from HIGH to LOW.

Selecting 0 for preset will use the _default_ action. If you find that the default action is _inverted_ for switch, please create presets for On and Off actions and assign them appropriately.

For assigning [Presets](/features/presets) to buttons use _Time & Macros_ settings page.

Note: Button 0 has two, built-in functions. 1. Hold it down for >6 seconds and the Wi-Fi settings will be reset to default. 2. Hold it down for >12 seconds and flash memory is erased.

### Analog Button

Starting in WLED 0.13, analog "buttons" (e.g. a potentiometer) are supported.
With the Short and Long columns set to 0, set the Double column in Button Actions to one of these values to configure:

| Property | Value |
| --- | --- |
Global brightness | 250
Effect speed | 249
Effect intensity | 248
Palette | 247
Primary color hue | 200
Segment N opacity | 0-32

This potentiometer should be supplied 3.3V and GND, with it's output supplied to A0 (or any other ADC pin you specify), recommended 10KΩ or greater. 

!!! info "Do not use ESP32 ADC2 GPIO pins for analog buttons"
    On ESP8266, you can only have a single analog button on pin A0, the pin set in the settings UI is ignored.  
    On ESP32, only ADC1 pins will work for analog input while WiFi is active (pins 32-39). ADC2 pins will not work.

#### Global Brightness

Users planning to use a potentiometer for global brightness should be aware that wled is configured to turn off when the potentiometer is adjusted to either extreme - both maximum and minimum adjustments. Users who desire to disable this functionality may do so on the hardware side by adding resistors between the potentiometer and the rails.

Adding a resistor between the potentiometer and 3.3V prevents A0 from fully reaching 3.3V and allows the potentiometer to be adjusted to the maximum adjustment without powering off wled. A value of 7.5%-10% of the potentiometer value should be sufficient for this (~750Ω for a 10KΩ potentiometer). Similarly, added resistance between the potentiometer and GND prevents A0 from reaching 0V, and allows the potentiometer to be adjusted to the minimum adjustment without powering off wled. A value of 3-5% of the potentiometer value should be sufficient (~500Ω for a 10KΩ potentiomenter).

In both instances, the added resistances will slightly reduce the overall adjustment range, with a larger reduction for larger resistor choices. As such, A user who desires the maximum possible adjustment range should determine their needed resistance values experimentally by installing the potentiometer, adjusting for stable behavior at the desired extrema, measuring the voltage on A0, using the voltage divider equation to determine the optimal resistance, then retesting for confirmation.



---
title: Multi-strip Support
hide:
  # - navigation
  # - toc
---

## Multi strip support

Starting in WLED 0.12.0, you are able to use multiple LED outputs from one ESP board!
Pins and LED numbers can be easily configured in LED settings, you don't need to re-compile code for your specific setup. Custom binaries for multiple pins are now also a thing of the past!

There are a few tips and recomendations to keep in mind when designing your setup:

### General

- It is highly recommended to use an ESP32 when using more than 1 output
- You may freely choose the LEDs type, pin numbers, length and color order of your LED strips at runtime in the LED settings page
- You cannot use input-only pins for LEDs output
    - classic esp32: pins 34 through 39 are input only.
    - esp32-s2: pin 46 is input only.
    - esp32-s3 and esp32-c3 don't have any input-only pins.
- Highly recommended to size power supply correctly according to your setup and disable the WLED brightness limiter setting to increase framerate with very large LED counts
- Most strip types have yet to be tested. Add confirmed working below:
- Confirmed working: WS281x, SK6812 RGBW, PWM white

### ESP8266

- There is a maximum of 3 strips supported.
- It is highly recommended to use two specific LED pins, GPIO1 (TX) and GPIO2 (D4), since they allow for hardware driving.
- It is recommended to use 512 LEDs/pin for good performance for a total of 1024 LEDs.
- 800 LEDs/pin for a total of 1600 has been confirmed working, but is not recommended for good performance and reliability.
- Using GPIO1 will disable serial debugging. If you need it, you can't use a strip on this pin.
- GPIO3 (RX) is the third pin that allows hardware driving on ESP8266. However, it uses 5 times as much memory per LED as GPIO 1 and 2, so use it only for low LED counts (recommended <50)
- You can use any other pin, but it will use the bitbang method, which is not recommended for reliability. It is best to stick to GPIO 1, 2, and if need be, 3.
- Using pin GPIO16 for WS2812b LEDs did not work in my testing.
- ESP8266 can calculate about 15k LEDs per second (that means 250LEDs @~60fps, 500 LEDs @~30fps, 1000 LEDs @~15fps)
- The LED settings will give you a bar that shows how much memory you can allocate.

### ESP32

- There is a maximum of 10 strips supported on "classic" ESP32 (dual core) boards. In audioreactive builds, you can use up to 9, because the audio input driver needs one of the hardware units that is normally available for driving LEDs.
 - * "classic" ESP32: 17 led strips (8 RMT + 8 parallel I2S + 1 single I2S, 16 with audioreactive)
 - * ESP32-S3: 12 led strips (with parallel I2S)
 - * ESP32-S2: 12 led strips (with parallel I2S, 4 with audioreactive)
 - * ESP32-C3: 2 led Strips
 - * (experimental) ESP32-C6, ESP32-C5, ESP32-P4: currently only 1 LED strip due to driver problems
- Contrary to the ESP8266, the pin usage does not matter on ESP32, feel free to use any available pin, except for input-only pins.
- For perfect performance, it is recommeded to use 512 LEDs/pin with 4 outputs for a total of 2048 LEDs.
- For very good performance, it is recommended to use 800 LEDs/pin with 4 outputs for a total of 3200 LEDs.
- For good performance, you can use 1000 LEDs/pin with 4 outputs for a total of 4000 LEDs.
- For okay performance, you can use 1000 LEDs/pin with 5 outputs for a total of 5000 LEDs.
- For okay performance, you can use 800 LEDs/pin with 6 outputs for a total of 4800 LEDs.
- ESP32 can calculate about 65k-85k LEDs per second (that means 1000 LEDs @~70fps, 2000 LEDs @~35fps, 4000 LEDs @~18fps)
- 4 outputs seem to be the sweet spot. 

### Virtual LEDs (DDP)

See [Virtual Leds](/advanced/ddp)



---
title: Palettes
hide:
  # - navigation
  # - toc
---

!!! info "Version Info"
    Beginning in 0.14 up to 10 [Custom Palettes](#custom-palettes) can be uploaded. Starting in v16.0, over 100 custom palettes are supported, a new palette editor is built into the UI, and over 800 additional palettes from the cpt-city collection are available.



|  ID | Name           | Description                                                                                                                                                                                           |
|----:|----------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|   0 | Default        | The palette is automatically selected depending on the effect. For most effects, this is the primary color<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_00.gif) |
|   2 | Color 1        | A palette consisting only of the primary color<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_02.gif)                                                             |
|   4 | Color Gradient | A palette which is a mixture of all segment colors<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_04.gif)                                                         |
|   3 | Colors 1&2     | Consists of the primary and secondary color<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_03.gif)                                                                |
|   5 | Colors Only    | Contains primary, secondary and tertiary colors<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_05.gif)                                                            |
|   1 | Random Cycle   | The palette changes to a random one every few seconds. Subject to change<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_01.gif)                                   |
|  18 | Analogous      | Red running on blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_18.gif)                                                                                        |
|  46 | April Night    | Dark blue background with colorful snowflakes<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_46.gif)                                                              |
|  63 | Aqua Flash     | Aqua gradient with a flash of yellow and white<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_63.gif)                                                             |
|  51 | Atlantica      | Greens & Blues of the ocean<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_51.gif)                                                                                |
|  50 | Aurora         | Greens on dark blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_50.gif)                                                                                        |
|  55 | Aurora 2       | Aurora with some pinks & blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_55.gif)                                                                              |
|  39 | Autumn         | Three white fields surrounded by yellow and dim red<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_39.gif)                                                        |
|  22 | Beach          | Different shades of light blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_22.gif)                                                                             |
|  26 | Beech          | Teal and yellow gradient fading out<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_26.gif)                                                                        |
|  67 | Blink Red      | Dark blue to dark red gradient with burst of purple<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_67.gif)                                                        |
|  15 | Breeze         | Teal colors with varying brightness<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_15.gif)                                                                        |
|  48 | C9             | Christmas lights palette. Red - amber - green - blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_48.gif)                                                       |
|  52 | C9 2           | C9 plus yellow<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_52.gif)                                                                                             |
|  53 | C9 New         | C9, but brighter and with a less purple blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_53.gif)                                                               |
|  57 | Candy          | Vivid yellows, magenta, salmon and blues<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_57.gif)                                                                   |
|  70 | Candy2         | Faded gradient of yellow, salmon and blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_70.gif)                                                                  |
|   7 | Cloud          | Gray-blueish colors<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_07.gif)                                                                                        |
|  37 | Cyane          | Desaturated pastel colors<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_37.gif)                                                                                  |
|  24 | Departure      | Greens and white fading out<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_24.gif)                                                                                |
|  30 | Drywet         | Blue and yellow gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_30.gif)                                                                                   |
|  59 | Fairy Reaf     | Bright aqua to purple gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_59.gif)                                                                             |
|  35 | Fire           | White, yellow and fading red gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_35.gif)                                                                      |
|  10 | Forest         | Yellow and green hues<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_10.gif)                                                                                      |
|  32 | Grintage       | Yellow fading out<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_32.gif)                                                                                          |
|  28 | Hult           | White, magenta and teal<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_28.gif)                                                                                    |
|  29 | Hult 64        | Teal and yellow hues<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_29.gif)                                                                                       |
|  36 | Icefire        | Same as Fire, but with blue colors<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_36.gif)                                                                         |
|  31 | Jul            | Pastel green and red<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_31.gif)                                                                                       |
|  25 | Landscape      | Blue, white and green gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_25.gif)                                                                             |
|   8 | Lava           | Dark red, yellow and bright white<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_08.gif)                                                                          |
|  38 | Light Pink     | Desaturated purple hues<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_38.gif)                                                                                    |
|  65 | Lite Light     | Faint white and purple<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_65.gif)                                                                                     |
|  40 | Magenta        | White with magenta and blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_40.gif)                                                                                |
|  41 | Magred         | Magenta and red hues<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_41.gif)                                                                                       |
|   9 | Ocean          | Blue, teal and white colors<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_09.gif)                                                                                |
|  44 | Orange & Teal  | An Orange - Gray - Teal gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_44.gif)                                                                           |
|  47 | Orangery       | Orange and yellow tones<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_47.gif)                                                                                    |
|   6 | Party          | Rainbow without green hues<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_06.gif)                                                                                 |
|  20 | Pastel         | Different hues with very little saturation<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_20.gif)                                                                 |
|  61 | Pink Candy     | White, pinks and purple<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_61.gif)                                                                                    |
|  11 | Rainbow        | Every hue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_11.gif)                                                                                                  |
|  12 | Rainbow Bands  | Rainbow colors with black spots in-between<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_12.gif)                                                                 |
|  16 | Red & Blue     | Red running on blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_16.gif)                                                                                        |
|  66 | Red Flash      | Red gradient with burst of white in the center<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_66.gif)                                                             |
|  62 | Red Reaf       | Blue, aqua and red gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_62.gif)                                                                                |
|  68 | Red Shift      | Vibrant yellow to blue gradient with magenta, purple and red<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_68.gif)                                               |
|  69 | Red Tide       | Waves of yellow, orange and red<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_69.gif)                                                                            |
|  56 | Retro Clown    | Yellow to purple gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_56.gif)                                                                                  |
|  33 | Rewhi          | Bright orange on desaturated purple<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_33.gif)                                                                        |
|  14 | Rivendell      | Desaturated greens<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_14.gif)                                                                                         |
|  49 | Sakura         | Pink and rose tones<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_49.gif)                                                                                        |
|  60 | Semi Blue      | Dark blues with a bright blue burst<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_60.gif)                                                                        |
|  27 | Sherbet        | Bright white, pink and mint colors<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_27.gif)                                                                         |
|  19 | Splash         | Vibrant pink and magenta<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_19.gif)                                                                                   |
|  13 | Sunset         | Dark blue with purple, red and yellow hues<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_13.gif)                                                                 |
|  21 | Sunset 2       | Yellow and white running on dim blue<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_21.gif)                                                                       |
|  54 | Temperature    | Temperature mapping<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_54.gif)                                                                                        |
|  34 | Tertiary       | Red, green and blue gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_34.gif)                                                                               |
|  45 | Tiamat         | A bright meteor with blue, teal and magenta hues<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_45.gif)                                                           |
|  58 | Toxy Reaf      | Vivid aqua to purple gradient<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_58.gif)                                                                              |
|  23 | Vintage        | Warm white running on very dim red<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_23.gif)                                                                         |
|  43 | Yelblu         | Blue with a little yellow<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_43.gif)                                                                                  |
|  64 | Yelblu Hot     | Yellow, red, blue spectrum<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_64.gif)                                                                                 |
|  17 | Yellowout      | Yellow, fading out<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_17.gif)                                                                                         |
|  42 | Yelmag         | Magenta and red hues with a yellow<br />![](https://raw.githubusercontent.com/scottrbailey/WLED-Utils/master/gifs/PAL_42.gif)                                                                         |



### Custom Palettes

As of v0.14, up to 10 custom palettes can be uploaded in JSON files. Starting in **v16.0**, over **100 custom palettes** are supported but the palette numbering scheme has changed: custom palettes start at the number 200 downwards so you need to re-save your presets - palettes 255-201 are reserved for usermod palettes like Audio Reactive.

**v16.0** also introduces an improved **Palette Editor** (accessible from the palette icon below the color picker in the UI) to create and edit custom palettes directly in the UI. The editor lets you add colour stops, adjust positions - and can show what your work looks like on the LEDs in real time.

Custom palettes can also be uploaded by placing JSON files named `palette0.json` through `palette9.json` on the device via the file editor. The format closely resembles that of the palettes defined in `palettes.h` with a gradient position (0–255), red, green, blue for each colour stop. An example:

```json
{"palette":[
    0, 255,  33,   4,
   43, 255,  68,  25,
   86, 255,   7,  25,
  127, 255,  82, 103,
  170, 255, 255, 242,
  209,  42, 255, 22,
  255,  87, 255, 65]}
```

Once a palette file has been created, it can be uploaded to the controller using the `/edit` page (`http://[controller-ip]/edit`). Since version 16.0 the editor is accessible through the file icon below the color picker.

## Additional Palettes (v16.0+)

v16.0 includes over **800 palettes** that were hand-picked from the [cpt-city](https://phillips.shef.ac.uk/pub/cpt-city/) collection. They are available directly in the palette editor.



---
title: Particle System
---

The Particle System is a physics-based effects engine built into WLED. It simulates many independent particles — each with its own position, velocity, size, age and color — and renders them onto your LED strip or matrix in real time.

WLED includes both a **1D Particle System** (for strips) and a **2D Particle System** (for matrices). The code is highly optimized for speed so it can be used with well over a thousand particles at high frame rates.

Since the animations are based on particle properties with some sprinkled in randomness for a more natural behaviour, all "PS" effects are random and non-deterministic in nature: the visuals generated never repeat. If you want two segments with particle effects to look identical, use the [`Copy Segment`](/features/effects#other-new-effects) effect.

---

## How It Works

Each frame, the engine:

1. Spawns new particles and ages existing particles - old particles fade out and die
2. Updates every particle's position based on its current velocity and checks for wall collisions.
3. Applies forces (gravity, drag, wind, etc.) depending on the active effect.
4. Handles collisions between particles where enabled.
5. Renders particles onto the LED output using brightness fall-off from the particle center.

### Rendering

Particles of size "0" are rendered to a single pixel. A size of "1" uses two/four pixels for smooth movement.
Larger particles use squared-distance fall-off rendering: in 2D this means they render as shaded circles/ellipses.

The color of each particle is added on top of already rendered ones creating fluid animation - when using a diffuser to blur individual LEDs this creates very fluid and dynamic animations.

### Collisions

Particles can collide with walls or with other particles if enabled. The engine uses mass-ratio based collision response: a larger particle pushes a smaller one proportionally to the mass difference, rather than applying equal and opposite forces. This makes interactions feel more physically realistic.

When collisions are enabled, each particle needs to check the proximity to each other particle: this can result in tens of thousands of checks for every frame and uses a lot of processing power. The rendering speed can therefore slow down significantly. Reducing the number of particles using the effect sliders is recommended if collisions are enabled.

---

## 1D Particle System

The 1D Particle System works on standard 1D LED segments. Effects include things like sparks, rain, fire, and bouncing balls along a single strip.

**2D mapping:** 1D particle effects support the `map1D2D` option, which maps the 1D output onto a 2D segment using various patterns. This lets you use 1D physics effects on a matrix.

---

## 2D Particle System

The 2D Particle System requires a 2D segment configured in WLED. Effects render directly onto the X/Y grid of the matrix.

Available 2D particle effects include fire, fireworks, meteor, galaxy, waterfall, ballpit, and more.

---

## Memory Usage

The Particle System allocates memory dynamically per segment based on the number of used particles which depends on the effect and segment size. On larger setups with many particles or multiple segments, PSRAM is recommended. The particle system will try its best to run if not enough RAM is available by reducing the particle count automatically - if even that fails the effect fails and falls back to "Solid".

---

## Effect Controls

Since particle effects are based on physics parameters they can be tuned a lot more than normal effects by using the effect sliders.
Each effect uses different slider controls such as:

- Gravity strength and direction
- Particle size
- Particle lifetime / spawn rate
- Collision on/off
- Wrap-around edges on/off

The default slider settings were chosen such that the effect looks nice on many different setups but often can be optimized for a specific situation. A description of what each slider/checkmark does for each effect is described in the [WLED effects list](/features/effects).



---
title: Segments
hide:
  # - navigation
  # - toc
---

!!! info
    Starting in WLED 0.9.0, Segments are supported.

This feature allows you to set different zones on the LED strip, each running a different effect or color.

A segment is selected if the checkmark next to the segment number is checked. Changes you make to color or effects will apply to all selected segments. The color/effect that is shown in the web UI is that of the first selected segment.

There is one _main segment_, Segment 0 by default. This segment has a few important differences to the rest of the segments:

- Color transitions only work on the main segment
- The main segment's color is the one that will be reported to HTTP and MQTT APIs

Tip: If you divide your strip into two segments, reverse the second one and select both, you can achieve very nice symmetrical effects!

Segment 0 has a Start LED of 0 and a Stop LED equal to the LED Count you defined in Configuration, LED Preferences. _The Stop LED is **not** included in the Segment._ Currently you can create a maximum of 10 segments in WLED 0.15 and earlier. Starting in v16.0, the segment limit was significantly increased.  Presets 1-15 use only Segment 0 by default.  Preset 16 is the only Preset that saves settings for Segments 1-10.

To display segment information select the down arrow in the Segment box.  To add a Segment select “+ Add Segment”.  Enter the Start and Stop LED as appropriate.  Grouping and Spacing control the organization of the LEDs within the selected effect.  To reverse the direction of an effect select Reverse Direction.  To delete a Segment select the trash can.  To save your Segment settings select the checkmark to the right of the Start and Stop LED numbers.

## Grouping and Spacing
When an effect changes the color of one LED, it is really changing the color of one LED group. Since the default group size is one, the effect normally only changes a single LED. When Grouping is set to two, the effect will light two LEDs using the same color. The two LEDs are treated as a single _virtual_ LED. 

To illustrate this, we can create a segment with 12 LEDS (physically referred to as LED 0 to LED 11) and select an effect that repeats three colors. When Grouping is set to one we see a repeating pattern of one red LED, one blue LED, and one green LED. When Grouping is set to two the segment of 12 physical LEDs becomes a segment of 6 virtual LEDs (virtualLED 0 to virtualLED 5). The same effect will now set the color of each virtual LED (which consists of two physical LEDs). The pattern becomes two red LEDs followed by two blue LEDs then two green LEDs.

|Setting|LED Output|
| :---: | --- |
|Grouping 1<br /> Spacing 0| ![](https://github.com/twlare/WLEDDocs/raw/master/G1S0A.png) |
|Grouping 2<br /> Spacing 0| ![](https://github.com/twlare/WLEDDocs/raw/master/G2S0Virtual.png) |

As the pattern cycles, the group of LEDs will move together.

|Setting|LED Output|
| :---: | --- |
|Grouping 1<br /> Spacing 0| ![](https://github.com/twlare/WLEDDocs/raw/master/G1S0Cycle.gif) |
|Grouping 2<br /> Spacing 0| ![](https://github.com/twlare/WLEDDocs/raw/master/G2S0Cycle.gif) |

Spacing controls the space or gap between LEDs. The default spacing is zero, so normally there is no space between LEDs. When Spacing is set to one, every other LED will be lit. The number of _virtual_ LEDs in the strip will be half the number of physical LEDs.

Again, we can create a segment with 12 LEDS (physically referred to as LED 0 to LED 11) and select an effect that repeats three colors. When Spacing is set to zero we see a repeating pattern of one red LED, one blue LED, and one green LED. When Spacing is set to one the segment of 12 physical LEDs becomes a segment of 6 virtual LEDs (virtualLED 0 to virtualLED 5). The same effect will now set the color of each virtual LED (which consists of the even numbered physical LEDs). The pattern becomes one red LED followed by a blank LED, one blue LED followed by a blank LED, then one green LED followed by a blank LED.

|Setting|LED Output|
| :---: | --- |
|Grouping 1<br /> Spacing 0| ![](https://github.com/twlare/WLEDDocs/raw/master/G1S0A.png) |
|Grouping 1<br /> Spacing 1| ![](https://github.com/twlare/WLEDDocs/raw/master/G1S1Virtual.png) |

As the pattern cycles, only the virtual LEDs will be lit - the blank LEDs in between the virtual LEDs will always be off.

|Setting|LED Output|
| :---: | --- |
|Grouping 1<br /> Spacing 0| ![](https://github.com/twlare/WLEDDocs/raw/master/G1S0Cycle.gif) |
|Grouping 1<br /> Spacing 1| ![](https://github.com/twlare/WLEDDocs/raw/master/G1S1Cycle.gif) |

Grouping and Spacing can be combined to create many different custom LED layouts. In the example below, the strip of 12 physical LEDs has been configured to function as four virtual LEDs with a small gap between them.

|Setting|LED Output|
| :---: | --- |
|Grouping 2<br /> Spacing 1| ![](https://github.com/twlare/WLEDDocs/raw/master/G2S1A.png) |
|Grouping 2<br /> Spacing 1| ![](https://github.com/twlare/WLEDDocs/raw/master/G2S1Cycle.gif) |

## Interleaving
This is an easy way to get a repeating pattern of colors using one segment per color.

![](../assets/images/content/segments-interleave.png)

## Offset in a segment
By default effects start in the first LED in the segment and finish in the last one. If the offset parameter in a segment is used, the effect start will be moved by the number of positions entered. It will continue to the last LED and then finish with the initial positions that were skipped.

For instance, let's assume assume a strip of 12 LEDs with the positions numbered as follows (like the examples above):

![](https://github.com/twlare/WLEDDocs/raw/master/LEDS12.png)

An offset value of 5 will make the effect start in the physical position 5, continue to position 11 and then finish with positions 0 through 4, like this:

![](https://github.com/twlare/WLEDDocs/raw/master/LED7to6.png)

A negative offset value is allowed and represents an offset starting from the last position in the segment. In our previous example, an offset of -2 will start the effect in position 10, like this:

![](https://github.com/twlare/WLEDDocs/raw/master/LED2to1.png)

The offset values is prioritized over grouping and/or spacing. For example, if the offset is 2, grouping 4 and spacing 1, the first group of 4 LEDs will start at the physical position number 2.

## Segment Layering & Effect Overlay

Since v16.0, WLED supports true segment layering: segments with overlapping pixels are composited in real time using a blend mode you choose per segment. This makes it possible to combine almost any two effects on the same LEDs.

To use layering, create two or more segments that cover the same pixel range. On each segment, select its **blend mode** from the dropdown:

| Mode | Description |
|------|-------------|
| Top/Default | Shows only the top layer, ignoring the bottom entirely |
| Bottom/None | Shows only the bottom layer, ignoring the top entirely |
| Add | Adds colors together, clamping at white |
| Subtract | Subtracts the top from the bottom, darkening toward black |
| Difference | Absolute difference — identical colors go black, opposites go bright |
| Average | 50/50 blend of both layers |
| Multiply | Multiplies colors — white passes bottom through, black blocks it |
| Divide | Divides bottom by top — brightens where the top is dark |
| Lighten | Picks the brighter pixel from each layer |
| Darken | Picks the darker pixel from each layer |
| Screen | Inverse of multiply — always brightens |
| Overlay | Boosts contrast using the bottom layer's brightness |
| Hard Light | Like Overlay, but driven by the top layer |
| Soft Light | Subtle contrast and saturation boost, no clipping |
| Dodge | Brightens the bottom based on the top |
| Burn | Darkens the bottom based on the top |
| Stencil | Shows top where it has any color; shows bottom where top is black |

The compositing order follows segment ID order: the segment with the **lower** ID is treated as the bottom (background) layer.

### Transition Blending

v16.0 also adds transition blending styles that control how effects cross-fade when you switch presets. Options include Shift, Push, and others, in addition to the classic dissolve-style fade.


---
title: Settings
hide:
  # - navigation
  # - toc
---

Web-configurable settings are split in multiple sub-pages. This page is meant to clarify the purpose of each setting.

## WiFi Settings

This sub-page offers options to connect the ESP to different WiFi/WLAN devices. (This section applies to WLED 0.8.5.)

| Setting name | Value Range | Description |
|---|---|---|
Network Name | String 0..32 | The name (SSID) of your home WiFi. Spaces and some other characters are not supported.
Network password | String 0..64 | The password of your home WiFi
Static IP | 4x 0..256 | An optional static IPv4 address
Static gateway | 4x 0..255 | In a static config, your gateway's IPv4 address
Static subnet | 4x 0..255 | In a static config, this normally is 255.255.255.0
mDNS address | String 0..32 | Name of your device for the Bonjour/Zeroconf protocol
Client IP | - | The current IP of the ESP in the home network
AP SSID | String 0..32 | The name of the ESPs internal WiFi hotspot (Access Point)
Hide AP name | Y/N | The ESPs Access Point won't appear in WiFi lists of other devices
AP password | String 0..64 | The password of the ESPs WiFi Access Point
AP WiFi channel | 1..13 | The 2.4G WiFi band of the AP. For advanced users
AP opens | select | Condition on when to open the AP
AP IP | - | The Access Point IPv4 address of the ESP (is 192.168.4.1 in most cases)
WiFi sleep | Y/N | Disabling WiFi sleep can increase reliability, but increases power consumption

## LED Preferences

This sub-page configures your LED & Hardware setup. (This section applies to WLED 0.14.1.)

| Setting name | Value Range | Default | Description |
|---|---|---|---|
Enable automatic brightness limiter | on/off | on | Have WLED automatically reduce overall brightness so that maximum current draw from the power supply stays below a specified level
Maximum current | 300–65000 mA | 850 mA | Maximum allowable current draw that WLED will target [*only appears if "Enable automatic brightness limiter" is on*]
LED voltage | multiple options | "5V default (55mA)" | Voltage/type of LEDs [*only appears if "Enable automatic brightness limiter" is on*]
Custom max. current | 1–255 | 50 | Current draw of a single LED pixel set to full white [*only appears if "LED voltage" is set to "Custom"*]

### Hardware Setup

#### LED outputs

WLED supports multiple outputs. To add an output, click the plus button at the bottom of the "LED outputs": section; to remove the last output, click the minus button. Bellow the plus/minus buttons is an indication of how much of the memory allocated to LEDs is being used by the configuration.

All outputs share the same address space within WLED. By default, the first pixel of an output will be given an address that is one higher than the last pixel of the previous output, but this can be altered.

Each output has the following settings:

| Setting name | Value Range | Default | Description |
|---|---|---|---|
Type (represented by the output's number) | multiple options | WS281x | Select the type of LEDs this output will be controlling
Clock | multiple options | "Normal" | Select the PWM or SPI frequency used when driving supported LEDs <br> Used PWM frequencies for the ESP8266 / ESP32, and SPI respectively; <br> Slowest: 293.33 Hz / 6510.33 Hz / 1 MHz <br> Slow: 440 Hz / 9765.50 Hz / 2 MHz <br> Normal: 880 Hz / 19531 Hz / 5 MHz <br> Fast: 1760 Hz / 39062 Hz / 10 MHz <br> Fastest: 2640 Hz / 58593 Hz / 20 MHz <br> [*only appears if "Type" is set to a type that is controlled by PWM or SPI*]
Color order | muliple options | "GRB" | Select which order your LEDs process color information (e.g. if your LEDs display red and green swapped, try changing it) [*only appears if "Type" is set to a type that supports color order*]
Start/Index | integer | cummulative length of all previous outputs | Define which address this output (or its first pixel) should use within WLED's address space [*only editable if "Custom bus start indices" is on*]
Length | integer | 1 | Define how many pixels are connected to this output [*only appears if "Type" is set to a type that supports multiple pixels*]
(Data/Clk) GPIO(s) | integer | (blank) | Tell WLED which GPIO pin(s) this output is connected to [*number and description of GPIO settings will depend on the output's selected type*]
Reversed (rotated 180°) | on/off | off | Mirrors the LEDs (last LED is first) [*only appears if "Type" is set to a type that supports multiple pixels*]
Skip first LEDs | 0–length | 0 | Will turn off the first one or more LEDs and shift those remaining by that number (e.g. if the first LEDs are only used as a signal repeater) [*only appears if "Type" is set to a type that supports multiple pixels*]
Off Refresh | on/off | off (typically) | WLED doesn't send out data if all of its outputs are off, but some pixels (notably TM1814) will go into a demo mode after a period of inactivity, and setting forces WLED to periodically send out additional "off" commands [*only appears if "Type" is set to a type that supports multiple pixels; default is "on" if "Type" is set to "TM1814"*]
Inverted output | on/off | off | Invert the output's state (i.e. if the output is bright when it's supposed to be dark, set this to "on") [*only appears if "Type" is set to a type that supports output inversion*]
IP address | IPv4 | (blank) | Set the IP address where the output data should be sent to [*only appears if "Type" is set to a type that supports network output*]
Auto-calculate white channel from RGB | multiple options | "None" | Selects whether WLED should attempted to generate white-channel information for colors that are only defined as red, green, and blue values [*only appears if "Type" is set to a type that has a white channel, including white-only types like "PCM White"*]

The following settings apply to all LED outputs:

| Setting name | Value Range | Default | Description |
|---|---|---|---|
Make a segment for each output | on/off | off | Will automatically create a segment for each output, including the correct Start LED and Stop LED settings
Custom bus start indices | on/off | off| When on, custom "Start" or "Index" values can be set for each output (e.g. output 2 can be set so that it shows up as LED address 200 regardless of output 1's length)
Use global LED buffer | on/off | on | Improves the performance of WLED-wide brightness controls (including Automatic Brightness Limiting) at the expense of additional memory usage

Additionally, one or more Color Order Overrides can be defined by clicking the plus button. This is useful when you have LEDs with two different color orders sharing the same output. The following settings are available for each override:

| Setting name | Value Range | Default | Description |
|---|---|---|---|
Start | integer | 0 | Define which address this color override should start it
Length | integer | 1 | Define how many pixels in a row should have their color setting overridden
Color order | muliple options | "GRB" | Same as "Color order" above

### Other settings

(This section applies to WLED 0.8.5; some of these settings no longer appear in 0.14.1.)

| Setting name | Value Range | Description |
|---|---|---|
Turn on after power up | Y/N | Whether the lights should turn on after a reset
Apply preset | 0..16 | Preset to load at boot (0 = none)
Use Gamma for brightness | Y/N | Will correct brightness changes to make it appear more linear. Advised to leave off
Use Gamma for color | Y/N | Will correct colors to match those on a monitor. Strongly advised to keep on
Brightness factor | 1..255 | Factor to change master brightness if it is too dim/bright for a certain configuration
Crossfade | Y/N | Whether to have a smooth fading transitional effect when changing colors/brightness
Transition time | 0..65535 | How many milliseconds the transition lasts
Enable transition for secondary color | Y/N |
Enable Palette transitions | Y/N | Enable transitions for palettes (not affected by transition time)
Timed light duration | 1..255 | How long the nightlight should stay on
Target brightness | 0..255 | What brightness the light should have after time is over. 0=off.
Fade down | Y/N | Gradually fades down the light over the duration instead of turning it off at the end
Palette blending | select | Choose how the palette wraps at the end (seam)

## User Interface settings

This sub-page changes the look of the web interface. (This section applies to WLED 0.8.5.)

| Setting name | Value Range | Description |
|---|---|---|
Server description | String 1..32 | The name of the device as shown on the top of the UI. Differs from Alexa device name
Sync button toggles... | Y/N | If enabled, both send and receive are toggled by the button in UI. If disabled, only sending is toggled and receiving is kept as configured in Sync settings.

## Sync settings

This sub-page configures external software synchronization interfaces. (This section applies to WLED 0.8.5.)

| Setting name | Value Range | Description |
|---|---|---|
On/Off button enabled | Y/N | Check if there is a physical pushbutton connected to GPIO0
Infrared receiver type | select | Type of infrared receiver
Broadcast UDP port | 1..65535 | All WLED lights you want to group together must have the same port
Receive Brightness | Y/N | If there is a sync notification, whether its brightness should be applied
Color | Y/N | Whether the color of the synced device should be applied
Effects | Y/N | Whether the effect settings should be applied
Send on direct change | Y/N | Whether to send a sync notification when state changed via web UI or API
Send on button press | Y/N | Whether to send sync when toggled by button or IR
Send Alexa notifications | Y/N | Whether to send sync after changed by Alexa (you may use Alexa groups instead)
Send Hue notifications | Y/N | Whether to send sync after a connected Philips light changed
Send Macro notifications | Y/N | Whether to send sync after a macro was triggered
Send notifications twice | Y/N | Sends notifications twice (if you have issues with UDP packet loss)
Receive UDP realtime | Y/N | Receive live UDP stream data (DRGB, WARLS, ...)
Use E1.31 multicast | Y/N | Listen on multicast IP instead of unicast
E1.31 start universe | 1..63000 | Only applies for multicast. If you want to set different content, set ESPs at least 8 universes apart
Timeout | 100..65000 | Time after which to resume normal mode once stream has stopped. 65000 will keep the data indefinitely
Force max brightness | Y/N | Realtime stream with max. brightness (unless limited by power brightness limiter)
Disable realtime gamma correction | Y/N | Check if your host software does gamma correction already
Realtime LED offset | -255..255 | Shift the realtime input by how many LEDs
Emulate Alexa device | Y/N | Allows you to control the light via the Amazon Echo voice assistant. Requires reboot
Alexa Invocation name | String 1..32 | The name you want the device to have for control via Alexa. Choose something easy she can understand
MQTT Broker | IP or String 0..32 | Connect to this host MQTT broker
Device topic | String 0..32 | MQTT topic unique to this light
Group topic | String 0..32 | MQTT topic for all lights in a group (room, floor, ...)
Hue Bridge IP | 4x 0..255 | Your Hue bridge IPv4 address. Should be static to avoid reassigning
Poll Hue light | 0..99 | The ID of the hue lamp you want to sync WLED to
every x ms | 100..65000 | How often to poll. Smaller numbers decrease lag but might hurt bridge responsiveness
... | Y/N | Turn polling on/off
Receive On/Off | Y/N | Turn on/off like the hue light
Brightness | Y/N | Set brightness to that of the hue light
Color | Y/N | Set color to that of the hue light
Hue status | - | Shows the current connection status to a hue bridge
Baud rate | Various | Set the default Serial connection Baud Rate

## Time settings

This sub-page configures automation tasks. (This section applies to WLED 0.8.5.)

| Setting name | Value Range | Description |
|---|---|---|
Get time from NTP | Y/N | Whether to get the current time from the internet
Use 24h format | Y/N | Use 24h clock format instead of AM/PM
Time zone | - | Your time zone. Open an issue if yours is unsupported. DST is applied automatically
UTC offset | -65000..65000 | Seconds to offset. If you want e.g. 1h offset, use 3600
Current local time | - | The local time the ESP has acquired. If set up correctly, should equal actual time
Clock overlay | - | The special overlay to use. Allows to display a clock on the strip
Countdown mode | Y/N | Allows to have a visual countdown towards a specific date
API macro fields | 16x String 0..64 | Allows you to define custom API calls which can be triggered by events
Boot Macro | 0..16 | Which macro to trigger after WiFi connected (0 is default action)
Alexa On/Off Macros | 2x 0..16 | Which macros to trigger when turning on/off via Alexa
Button Macro | 0..16 | Macro to trigger if button is short pressed. Default action is on/off toggle.
Long Press | 0..16 | Macro to trigger if button is long pressed (>0.7s).  Default action is random color.
Double press | 0..16 | Macro for double click on button.
Countdown-Over Macro | 0..16 | Macro to trigger when the countdown is over
Timed-Light-Over Macro | 0..16 | Macro to trigger when timed light is done

## Security settings

This sub-page manages permissions and updates. (This section applies to WLED 0.8.5.)

| Setting name | Value Range | Description |
|---|---|---|
Enable OTA lock | Y/N | If enabled, no firmware updates may be done via WiFi and some settings can't be changed.
Passphrase | String 0..32 | To disable OTA lock, you need a password. The default is "wledota". Change it!
Deny access to WiFi settings | Y/N | Disables changes to WiFi settings while locked
Disable recovery AP | Y/N | If enabled, the module will not open an Access Point if connection to home WiFi failed.
Factory reset | Y/N | Deletes all custom settings data (passwords, configuration, macros, presets)
Manual OTA | - | If OTA is enabled, you can upload new binary firmware
Enable ArduinoOTA | Y/N | Useful for developers. Be careful, can even be left on when OTA locked!


---
title: Web GUI Sitemap
hide:
  # - navigation
  # - toc
---

This is the sitemap of the module server.
Access with \<ESP-IP\>/path (Example: **192.168.8.4/settings**)

| Path | Description | OTA rights required | Since version |
| --- | --- | --- | --- |
/ | Default UI, index page | No | 0.2
/update | Upload new firmware | Yes | 0.3
/win | HTTP Request API (since 0.3) | No | 0.3
/json | JSON API | No | 0.8.4
/json/state | JSON state object | No | 0.8.4
/json/info | JSON information | No | 0.8.4
/json/eff | Effect name list | No | 0.8.4
/json/pal | Palette name list | No | 0.8.4
/json/live | Current colors of LEDs | No | 0.9.0
/liveview | Live preview of current LEDs | No | 0.9.0
/settings | Settings index page | No | 0.2
/settings/wifi | WiFi Settings page | Cnfg | 0.5.0
/settings/led | LED Settings page | No | 0.5.0
/settings/ui | UI Settings page | No | 0.5.0
/settings/sync | Sync Settings page | No | 0.5.0
/settings/time | Time Settings page | No | 0.5.0
/settings/sec | Security Settings page | Yes | 0.5.0
/welcome | New User Welcome page | No | 0.5.0
/sliders | UI, index page | No | 0.5.0
/reset | Reboot module | No | 0.3
/version | Returns build version | No | 0.3
/uptime | Returns runtime in ms | No | 0.4
/freeheap | Returns free memory | No | 0.4
/favicon.ico | Page icon | No | 0.2
/teapot | :) | No | 0.5.0
/edit | Filesystem editor | Yes | 0.2
/u | Custom usermod page | 0.8.4 (?)
/cpal.htm | Custom palette editor | 0.14.0-b3
/pixart.htm | 2D Pixel Art converter (not compiled by default) | 0.14.0-b3
/pxmagic.htm | 2D Image converter | 0.14.0-b4

#### Removed sites

| Path | Description | OTA rights required | Versions |
| --- | --- | --- | --- |
/list | Lists SPIFFS contents (if USEFS) | Yes | 0.2-0.8.3
/easter | Joke page | No | 0.6.2 only
/power | Returns an estimate of used LED current | No | 0.5.0-0.8.3
/build | Returns details about the build | No | 0.5.0-0.8.3
/cleareeprom | Resets to factory defaults | Yes | 0.3-0.6.4
/down | Kills software. Hard reset required. | Yes | 0.3-0.6.4
/url | Returns current light setup API url | No | 0.9.1-0.14.0-b3