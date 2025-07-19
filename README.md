# mqtty

`mqtty` bridges an MQTT topic to a local pseudoterminal (PTY), allowing you to interact with serial ports over MQTT as if they were local TTY devices.

This is useful for debugging, automation, or tunneling serial communication through a networked MQTT broker.

## Usage

```bash
mqtty mqtt://<host>/<topic> [--pts-only | --wrap-picocom]
```

You must choose one of the two modes:

* `--pts-only`, `-p`:
  Print the path to the PTS device and keep it open. Useful for tools or scripts that want to use the virtual serial port.

* `--wrap-picocom`, `-w`:
  Launch `picocom --quiet` attached to the PTS device. This allows interactive use of a remote serial port over MQTT.

The `<topic>` segment of the URI is used as the base path for MQTT messages:

* `.../device_serial_input` receives data from your local PTY (sent to the device)
* `.../device_serial_output` sends incoming data from the device to your PTY

## Example

```bash
mqtty mqtt://broker.local/mydevice --wrap-picocom
```

This opens a local PTS device, bridges it to `mydevice/device_serial_input` and `mydevice/device_serial_output`, and launches `picocom` on the virtual port.

## License

MIT
