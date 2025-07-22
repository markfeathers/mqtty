import os
import pty
import select
import threading
from typing import Any, Dict, Optional, Literal
from paho.mqtt.client import Client, MQTTMessage
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from paho.mqtt.enums import CallbackAPIVersion
from urllib.parse import urlparse
import sys
import argparse
import subprocess
import signal


class MQTTY:
    def __init__(self, mqtt_uri: str, use_pty: bool) -> None:
        self.mqtt_uri = urlparse(mqtt_uri)
        self.use_pty = use_pty

        if self.mqtt_uri.scheme not in ["mqtt", "ws", "wss"]:
            raise ValueError("Invalid URI scheme. Expected 'mqtt://', 'ws://', or 'wss://'.")

        self.mqtt_host = self.mqtt_uri.hostname
        self.mqtt_port = self.mqtt_uri.port or (443 if self.mqtt_uri.scheme == "wss" else 80)
        self.mqtt_transport: Literal["tcp", "websockets"] = (
            "websockets" if self.mqtt_uri.scheme in ["ws", "wss"] else "tcp"
        )

        base_path = self.mqtt_uri.path.lstrip("/")  # Remove leading slash from path
        self.device_serial_input_topic = f"{base_path}/device_serial_input"
        self.device_serial_output_topic = f"{base_path}/device_serial_output"

        self.mqtt_client = Client(
            transport=self.mqtt_transport,
            callback_api_version=CallbackAPIVersion.VERSION2,
        )

        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.slave_name: Optional[str] = None

        if self.use_pty:
            self.master_fd, self.slave_fd = pty.openpty()
            self.slave_name = os.ttyname(self.slave_fd)

        self.connected = False
        self.stop_event = threading.Event()

    def on_message(self, _client: Client, _userdata: object, msg: MQTTMessage) -> None:
        try:
            if self.use_pty and self.master_fd is not None:
                os.write(self.master_fd, msg.payload)
            else:
                sys.stdout.buffer.write(msg.payload)
                sys.stdout.buffer.flush()
        except Exception as e:
            sys.stderr.write(f"Error handling MQTT message: {e}\n")

    def mqtt_connect(self) -> None:
        self.mqtt_client.on_message = self.on_message

        def on_connect(
            client: Client,
            userdata: Any,
            flags: Dict[str, Any],
            reason_code: ReasonCode,
            properties: Optional[Properties],
        ) -> None:
            if reason_code == 0:
                self.connected = True
                client.subscribe(self.device_serial_output_topic)
            else:
                sys.stderr.write(f"Failed to connect to MQTT broker, return code {reason_code}\n")

        def on_disconnect(
            client: Client,
            userdata: Any,
            reason_code: ReasonCode | int | None,
            properties: Optional[Properties],
        ) -> None:
            self.connected = False

        self.mqtt_client.on_connect = on_connect
        self.mqtt_client.on_disconnect = on_disconnect

        if self.mqtt_host is None:
            raise ValueError("MQTT URI must include a hostname.")
        try:
            self.mqtt_client.connect_async(self.mqtt_host, self.mqtt_port)
            self.mqtt_client.loop_forever()
        except Exception as e:
            sys.stderr.write(f"MQTT connection failed: {e}\n")

    def pty_to_mqtt(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.master_fd is not None:
                    ready, _, _ = select.select([self.master_fd], [], [], 1)
                    if self.master_fd in ready:
                        data = os.read(self.master_fd, 1024)
                        if self.connected:
                            self.mqtt_client.publish(self.device_serial_input_topic, data)
            except Exception as e:
                sys.stderr.write(f"Error reading from PTY: {e}\n")
                break

    def start_threads(self) -> None:
        mqtt_thread = threading.Thread(target=self.mqtt_connect, daemon=True)
        mqtt_thread.start()

        if self.use_pty:
            pty_thread = threading.Thread(target=self.pty_to_mqtt, daemon=True)
            pty_thread.start()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        if self.use_pty:
            if self.master_fd is not None:
                os.close(self.master_fd)
            if self.slave_fd is not None:
                os.close(self.slave_fd)


def main() -> None:
    parser = argparse.ArgumentParser(description="MQTTY: Bridge MQTT to PTY.")
    parser.add_argument("mqtt_uri", help="MQTT URI (e.g., mqtt://broker/topic)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-p",
        "--pts-only",
        action="store_true",
        help="Only create and expose the PTS device",
    )
    group.add_argument(
        "-w",
        "--wrap-picocom",
        action="store_true",
        help="Wrap and run picocom on the PTS device",
    )
    group.add_argument(
        "-r",
        "--raw-output",
        action="store_true",
        help="Only print device_serial_output topic to stdout, no PTY or input",
    )
    args = parser.parse_args()

    try:
        if args.raw_output:
            bridge = MQTTY(args.mqtt_uri, False)
            bridge.start_threads()
            try:
                signal.signal(signal.SIGINT, lambda sig, frame: bridge.shutdown())
                signal.pause()
            except KeyboardInterrupt:
                bridge.shutdown()
            return

        bridge = MQTTY(args.mqtt_uri, True)
        if args.pts_only:
            print(bridge.slave_name, flush=True)
        bridge.start_threads()

        if args.pts_only:
            signal.signal(signal.SIGINT, lambda sig, frame: bridge.shutdown())
            signal.pause()  # Wait until interrupted
        elif args.wrap_picocom:
            try:
                if bridge.slave_name is not None:
                    subprocess.run(["picocom", "--quiet", bridge.slave_name])
                else:
                    sys.stderr.write("Error: slave_name is not set.\n")
            finally:
                bridge.shutdown()

    except ValueError as e:
        sys.stderr.write(f"Error: {e}\n")


if __name__ == "__main__":
    main()
